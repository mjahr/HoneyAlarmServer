#!/usr/bin/python
# Alarm Server
# Supporting Envisalink 2DS/3/4
# Original version for DSC Written by donnyk+envisalink@gmail.com,
# lightly improved by leaberry@gmail.com
# Honeywell version adapted by matt.weinecke@gmail.com
# Significant rewrite by michaelj@gmail.com
#
# This code is under the terms of the GPL v3 license.

import os
import sys
import json
import getopt
import logging
import re
import urlparse

from twisted.internet import reactor
from twisted.web.resource import Resource, NoResource
from twisted.web.server import Site
from twisted.web.static import File
from twisted.protocols.basic import LineOnlyReceiver
from twisted.internet.task import LoopingCall
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log

from envisalinkdefs import *
from baseConfig import BaseConfig
from smartthings import SmartThings
from datetime import datetime
from datetime import timedelta

ALARMSTATE = {}
MAXPARTITIONS = 16
MAXZONES = 128
MAXALARMUSERS = 47
shuttingdown = False


class AlarmServerConfig(BaseConfig):
    def __init__(self, configfile):
        # call ancestor for common setup
        super(self.__class__, self).__init__(configfile)

        self.ENVISALINKHOST = self.read_config_var('envisalink',
                                                   'host',
                                                   'envisalink', 'str')
        self.ENVISALINKPORT = self.read_config_var('envisalink',
                                                   'port',
                                                   4025, 'int')
        self.ENVISALINKPASS = self.read_config_var('envisalink',
                                                   'pass',
                                                   'user', 'str')
        self.ENVISAPOLLINTERVAL = self.read_config_var('envisalink',
                                                       'pollinterval',
                                                       0, 'int')
        self.ENVISAZONEDUMPINTERVAL = self.read_config_var('envisalink',
                                                           'zonedumpinterval',
                                                           60, 'int')
        self.ENVISAKEYPADUPDATEINTERVAL = self.read_config_var('envisalink',
                                                           'keypadupdateinterval',
                                                           60, 'int')
        self.ENVISACOMMANDTIMEOUT = self.read_config_var('envisalink',
                                                         'commandtimeout',
                                                         30, 'int')
        self.ENVISAKPEVENTTIMEOUT = self.read_config_var('envisalink',
                                                         'kpeventtimeout',
                                                         45, 'int')
        self.ALARMCODE = self.read_config_var('envisalink',
                                              'alarmcode',
                                              1111, 'int')
        self.LOGFILE = self.read_config_var('alarmserver',
                                            'logfile',
                                            '', 'str')
        self.LOGLEVEL = self.read_config_var('alarmserver',
                                             'loglevel',
                                             'DEBUG', 'str')

        self.PARTITIONNAMES = {}
        for i in range(1, MAXPARTITIONS + 1):
            self.PARTITIONNAMES[i] = self.read_config_var('alarmserver',
                                                          'partition' + str(i),
                                                          False, 'str', True)

        self.ZONENAMES = {}
        for i in range(1, MAXZONES + 1):
            self.ZONENAMES[i] = self.read_config_var('alarmserver',
                                                     'zone' + str(i),
                                                     False, 'str', True)

        self.ALARMUSERNAMES = {}
        for i in range(1, MAXALARMUSERS + 1):
            self.ALARMUSERNAMES[i] = self.read_config_var('alarmserver',
                                                          'user' + str(i),
                                                          False, 'str', True)

    def initialize_alarmstate(self):
        ALARMSTATE['zone'] = {}
        for zoneNumber in self.ZONENAMES.keys():
            zoneName = self.ZONENAMES[zoneNumber]
            if not zoneName: continue
            ALARMSTATE['zone'][zoneNumber] = {
                'name': zoneName,
                'message': 'uninitialized',
                'status': 'uninitialized',
                'closedSeconds': -1,
                'lastChanged': 'never'
            }

        ALARMSTATE['partition'] = {}
        for pNumber in self.PARTITIONNAMES.keys():
            pName = self.PARTITIONNAMES[pNumber]
            if not pName: continue
            ALARMSTATE['partition'][pNumber] = {
                'name': pName,
                'message': 'uninitialized',
                'status': 'uninitialized',
                'beep': 'uninitialized',
                'alarm': False,
                'alarm_in_memory': False,
                'armed_away': False,
                'ac_present': False,
                'bypass': False,
                'chime': False,
                'armed_max': False,
                'alarm_fire': False,
                'system_trouble': False,
                'ready': False,
                'fire': False,
                'low_battery': False,
                'armed_stay': False
            }


class EnvisalinkClientFactory(ReconnectingClientFactory):

    def __init__(self, config):
        self._config = config

    def buildProtocol(self, addr):
        logging.debug("%s connection established to %s:%s", addr.type, addr.host, addr.port)
        logging.debug("resetting connection delay")
        self.resetDelay()
        self.envisalinkClient = EnvisalinkClient(self._config)
        # check on the state of the envisalink connection repeatedly
        self._currentLoopingCall = LoopingCall(self.envisalinkClient.check_alive)
        self._currentLoopingCall.start(1)
        return self.envisalinkClient

    def startedConnecting(self, connector):
        logging.debug("Started to connect to Envisalink...")

    def clientConnectionLost(self, connector, reason):
        if not shuttingdown:
            logging.debug('Lost connection to Envisalink.  Reason: %s', str(reason))
            if hasattr(self, "_currentLoopingCall"):
                try:
                    self._currentLoopingCall.stop()
                except:
                    logging.error("Error trying to stop looping call, ignoring...")
            ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        logging.debug('Connection failed to Envisalink. Reason: %s', str(reason))
        if hasattr(self, "_currentLoopingCall"):
            try:
                self._currentLoopingCall.stop()
            except:
                logging.error("Error trying to stop looping call, ignoring...")
        ReconnectingClientFactory.clientConnectionFailed(self, connector,
                                                         reason)


class EnvisalinkClient(LineOnlyReceiver):
    def __init__(self, config):
        # Are we logged in?
        self._loggedin = False

        self._has_partition_state_changed = False

        # Set config
        self._config = config

        # config smartthings
        self._smartthings = SmartThings("alarmserver.cfg")

        self._commandinprogress = False
        now = datetime.now()
        self._lastkeypadupdate = now
        self._lastpoll = datetime.min
        self._lastzonedump = datetime.min
        self._lastpartitionupdate = datetime.min
        self._lastcommand = now
        self._lastcommandresponse = now

    def logout(self):
        logging.debug("Ending Envisalink client connection...")
        self._loggedin = False
        if hasattr(self, 'transport'):
            self.transport.loseConnection()

    def send_data(self, data):
        logging.debug('TX > ' + data)
        self.sendLine(data)

    def check_alive(self):
        if self._loggedin:
            now = datetime.now()

            # if too much time has passed since command was sent without a
            # response, something is wrong
            delta = now - self._lastcommand
            if (self._lastcommandresponse < self._lastcommand and
                delta > timedelta(seconds=self._config.ENVISACOMMANDTIMEOUT)):
                message = "Timed out waiting for command response, resetting connection..."
                logging.error(message)
                self._smartthings.sendError(message)
                self.logout()
                return

            # is it time to poll again?
            if self._config.ENVISAPOLLINTERVAL != 0:
                delta = now - self._lastpoll
                if (delta > timedelta(seconds=self._config.ENVISAPOLLINTERVAL) and
                    not self._commandinprogress):
                    self._lastpoll = now
                    self.send_command('00', '')

            # is it time to dump zone states again?
            delta = now - self._lastzonedump
            if (delta > timedelta(seconds=self._config.ENVISAZONEDUMPINTERVAL) and
                not self._commandinprogress):
                self._lastzonedump = now
                self.dump_zone_timers()

            # if 10 seconds have passed and we haven't received a keypad update,
            # something is wrong
            delta = now - self._lastkeypadupdate
            if delta > timedelta(seconds=self._config.ENVISAKPEVENTTIMEOUT):
                # reset connection
                message = "No recent keypad updates from envisalink, resetting connection..."
                logging.error(message)
                self._smartthings.sendError(message)
                self.logout()
                return


# application commands to the envisalink

    def send_command(self, code, data):
        if not self._loggedin:
            logging.error("Not connected to Envisalink - ignoring command %s",
                          code)
            return
        if self._commandinprogress:
            logging.error("Command already in progress - ignoring command %s",
                          code)
            return
        self._commandinprogress = True
        self._lastcommand = datetime.now()
        to_send = '^' + code + ',' + data + '$'
        self.send_data(to_send)

    def change_partition(self, partitionNumber):
        if partitionNumber < 1 or partitionNumber > 8:
            logging.error("Invalid Partition Number %d specified when trying "
                          "to change partition, ignoring.", partitionNumber)
            return
        self.send_command('01', str(partitionNumber))

    def dump_zone_timers(self):
        self.send_command('02', '')

    def keypresses_to_default_partition(self, keypresses):
        self.send_data(keypresses)

    def keypresses_to_partition(self, partitionNumber, keypresses):
        for char in keypresses:
            to_send = '^03,' + str(partitionNumber) + ',' + char + '$'
            logging.debug('TX > ' + to_send)
            self.sendLine(to_send)

    # network communication callbacks

    def connectionMade(self):
        logging.info("Connected to %s:%d" %
                     (self._config.ENVISALINKHOST,
                      self._config.ENVISALINKPORT))

    def connectionLost(self, reason):
        if not shuttingdown:
            logging.info("Disconnected from %s:%d, reason was %s" %
                         (self._config.ENVISALINKHOST,
                          self._config.ENVISALINKPORT,
                          reason.getErrorMessage()))
            if self._loggedin:
                self.logout()

    def lineReceived(self, input):
        if input != '':
            logging.debug('----------------------------------------')
            logging.debug('RX < ' + input)
            if input[0] in ("%", "^"):
                # keep first sentinel char to tell difference between tpi and
                # Envisalink command responses.  Drop the trailing $ sentinel.
                inputList = input[0:-1].split(',')
                code = inputList[0]
                data = ','.join(inputList[1:])
            else:
                # assume it is login info
                code = input
                data = ''

            try:
                handler = "handle_%s" % evl_ResponseTypes[code]['handler']
            except KeyError:
                logging.warning('No handler defined for ' + code + ', skipping...')
                return

            try:
                handlerFunc = getattr(self, handler)
            except AttributeError:
                raise RuntimeError("Handler function doesn't exist")

            handlerFunc(data)
            logging.debug('----------------------------------------')

    # Envisalink Response Handlers

    def handle_login(self, data):
        self.send_data(self._config.ENVISALINKPASS)

    def handle_login_success(self, data):
        self._loggedin = True
        logging.info('Password accepted, session created')

    def handle_login_failure(self, data):
        logging.error('Password is incorrect. Server is closing socket connection.')

    def handle_login_timeout(self, data):
        logging.error('Envisalink timed out waiting for password, whoops that '
                      'should never happen.  Server is closing socket connection')

    def handle_poll_response(self, code):
        self._lastpollresponse = datetime.now()
        self.handle_command_response(code)

    def handle_command_response(self, code):
        self._commandinprogress = False
        self._lastcommandresponse = datetime.now()
        responseString = evl_TPI_Response_Codes[code]
        logging.debug("Envisalink response: " + responseString)
        if code != '00':
            logging.error("error sending command to envisalink.  Response was: "
                          + responseString)

    def handle_keypad_update(self, data):
        self._lastkeypadupdate = datetime.now()
        dataList = data.split(',')
        # make sure data is in format we expect, current TPI seems to
        # send bad data every so ofen
        if len(dataList) != 5 or "%" in data:
            logging.error("Data format invalid from Envisalink, ignoring...")
            return

        partitionNumber = int(dataList[0])
        flags = IconLED_Flags()
        flags.asShort = int(dataList[1], 16)
        userOrZone = dataList[2]
        beep = evl_Virtual_Keypad_How_To_Beep.get(dataList[3], 'unknown')
        alpha = dataList[4]

        if partitionNumber not in ALARMSTATE['partition']:
            logging.debug("Skipping partition %d", partitionNumber)
            return

                # TODO: update status text based on bitfield
        # if (newStatus['alarm']):
        #     statusText == 'IN_ALARM'
        # elif (newStatus[
        #         'alarm_in_memory': statusText == 'ALARM_IN_MEMORY',
        #         'armed_away': statusText == 'ARMED_AWAY',
        #         # 'ac_present'
        #         'bypass': statusText == 'READY_BYPASS',
        #         # 'chime': statusText == '',
        #         'armed_max': statusText == 'ARMED_MAX',
        #         'alarm_fire': statusText == 'ALARM_FIRE',
        #         # 'system_trouble': statusText == '',
        #         'ready': statusText == 'READY',  # in ('READY', 'READY_BYPASS'),
        #         'fire': statusText == 'ALARM_FIRE',
        #         # 'low_battery': statusText == '',
        #         'armed_stay': statusText == 'ARMED_STAY',
        #         'status': statusText

        newStatus = {
            'alarm': bool(flags.alarm),
            'alarm_in_memory': bool(flags.alarm_in_memory),
            'armed_away': bool(flags.armed_away),
            'ac_present': bool(flags.ac_present),
            'bypass': bool(flags.bypass),
            'chime': bool(flags.chime),
            'armed_max': bool(flags.armed_zero_entry_delay),
            'alarm_fire': bool(flags.alarm_fire_zone),
            'system_trouble': bool(flags.system_trouble),
            'ready': bool(flags.ready),
            'fire': bool(flags.fire),
            'low_battery': bool(flags.low_battery),
            'armed_stay': bool(flags.armed_stay),
            'beep': beep,
            'message': alpha
         }

        now = datetime.now()
        delta = now - self._lastpartitionupdate
        if delta < timedelta(seconds=self._config.ENVISAKEYPADUPDATEINTERVAL):
            logging.debug('Skipping keypad update within update interval')
        else:
            # We shouldn't have to skip keypad update during command in
            # progress because we don't initiate another command.
            if self._commandinprogress:
                logging.warning('Keypad update while command in progress')
            self._lastpartitionupdate = now
            logging.debug("keypad_update: zone %s status %s", userOrZone, newStatus);
            # Update zone status if the keypad is reporting a fault.
            if alpha.startswith("FAULT") and not flags.ready:
                zoneNumber = int(userOrZone)
                self.updateZoneStatus(zoneNumber, "open")
            self.setPartitionStatus(partitionNumber, newStatus)

            # Send update to SmartThings
            self._smartthings.sendUpdate(ALARMSTATE)

    def updateZoneStatus(self, zoneNumber, zoneStatus):
        zoneName = self._config.ZONENAMES[zoneNumber]
        # only bother to update if zone name is defined in config
        if not zoneName:
            return False

        logmessage = ("%s (zone %i) is %s" % (zoneName, zoneNumber, zoneStatus))
        logging.debug(logmessage)
        statusChanged = (ALARMSTATE['zone'][zoneNumber]['status'] != zoneStatus)
        if statusChanged:
            logging.info("zone state change: " + logmessage)
            timeStr = self.getTimeText()
            ALARMSTATE['zone'][zoneNumber].update({
                'message': ("%s at %s" % (zoneStatus, timeStr)),
                'status': zoneStatus, 'closedSeconds': 0,
                'lastChanged': timeStr
            })
        return statusChanged

    def handle_zone_state_change(self, data):
        # Envisalink TPI is inconsistent at generating these
        logging.debug("handle_zone_state_change: data='%s'" % data)

        # Data is an 64-bit number in hex, little endian: 8 2-char bytes.
        leHex = data
        # Convert from little-endian to big-endian by reversing the order of the bytes
        beHex = "".join([leHex[2*i]+leHex[2*i+1] for i in range(7,-1,-1)])
        # Convert from hex to binary
        beBin = bin(int(beHex, 16))[2:].zfill(64)

        for zoneNumber in range(1,65):
            # zone numbers are 1-indexed.  big-endian means zone 1 is
            # the last bit, so zone i is the (64-i)th bit.
            zoneBit = beBin[64 - zoneNumber]
            zoneStatus = 'open' if zoneBit == '1' else 'closed'

            # zone_state_change will often continue reporting zones as
            # open when they have already closed, so we ignore open
            # zones here and instead rely on keypad update to tell us
            # when zones are open.
            if (zoneStatus == 'closed'):
                self.updateZoneStatus(zoneNumber, zoneStatus)

    def handle_partition_state_change(self, data):
        self._has_partition_state_changed = True
        for currentIndex in range(0, 8):
            partitionNumber = currentIndex + 1
            statusCode = data[currentIndex * 2:(currentIndex * 2) + 2]
            statusText = evl_Partition_Status_Codes[str(statusCode)]['name']

            # skip partitions we don't care about
            if (statusText == 'NOT_USED' or
                not self._config.PARTITIONNAMES[partitionNumber]):
                continue

            newStatus = {
                'alarm': statusText == 'IN_ALARM',
                'alarm_in_memory': statusText == 'ALARM_IN_MEMORY',
                'armed_away': statusText == 'ARMED_AWAY',
                # 'ac_present'
                'bypass': statusText == 'READY_BYPASS',
                # 'chime': statusText == '',
                'armed_max': statusText == 'ARMED_MAX',
                'alarm_fire': statusText == 'ALARM_FIRE',
                # 'system_trouble': statusText == '',
                'ready': statusText == 'READY',  # in ('READY', 'READY_BYPASS'),
                'fire': statusText == 'ALARM_FIRE',
                # 'low_battery': statusText == '',
                'armed_stay': statusText == 'ARMED_STAY',
                'status': statusText
            }
            logging.debug('partition %d status update: %s',
                          partitionNumber, newStatus)
            self.setPartitionStatus(partitionNumber, newStatus)

    def setPartitionStatus(self, partitionNumber, newStatus):
        statusMap = ALARMSTATE['partition'][partitionNumber]
        # compute list of all keys that are different between old and new status.
        # message change doesn't count as a state change.
        keyDiff = [key for key in newStatus
                   if (newStatus[key] != statusMap[key] and
                       key not in ('message', 'status'))]
        if len(keyDiff) > 0:
            logging.debug('Partition old status: ' + str(statusMap))
            statusMap['lastChanged'] = self.getTimeText()
            logging.debug('Partition state change: ' + str(statusMap))
            logging.debug('Partition key diff: ' + str(keyDiff))

        statusMap.update(newStatus)
        logging.debug('Partition %d status: %s', partitionNumber, str(newStatus))
        if statusMap['ready']:
            # close all zones and send a zone status update if necessary
            for zoneNumber, zoneInfo in ALARMSTATE['zone'].items():
                self.updateZoneStatus(zoneNumber, 'closed')

    def handle_realtime_cid_event(self, data):
        eventTypeInt = int(data[0])
        eventType = evl_CID_Qualifiers[eventTypeInt]
        cidEventInt = int(data[1:4])
        cidEvent = evl_CID_Events[cidEventInt]
        partition = data[4:6]
        zoneOrUser = int(data[6:9])

        logging.debug('Event Type is ' + eventType)
        logging.debug('CID Type is ' + cidEvent['type'])
        logging.debug('CID Description is ' + cidEvent['label'])
        logging.debug('Partition is ' + partition)
        logging.debug(cidEvent['type'] + ' value is ' + str(zoneOrUser))

    # returns the current time in a human-readable format, optionally
    # offset by a number of seconds.
    def getTimeText(self, secondsAgo=0):
        t = datetime.now() - timedelta(seconds=secondsAgo)
        return t.strftime("%Y-%m-%d %H:%M:%S")

    # note that a request to dump zone timers generates both a standard command
    # response (handled elsewhere) as well as this event
    def handle_zone_timer_dump(self, zoneDump):
        zoneInfoArray = self.convertZoneDump(zoneDump)
        for zoneNumber, zoneInfo in enumerate(zoneInfoArray, start=1):
            zoneName = self._config.ZONENAMES[zoneNumber]

            # skip zones we don't care about or that haven't changed state
            if (not zoneName or
                ALARMSTATE['zone'][zoneNumber]['status'] == zoneInfo['status']):
                continue

            logMessage = ("%s (zone %i) %s" % (zoneName, zoneNumber, zoneInfo))

            # Set lastChanged time to closedSeconds, which is 0 if open.
            zoneInfo['lastChanged'] = self.getTimeText(
                secondsAgo=zoneInfo['closedSeconds'])

            # zone dumps seem to be buggy and falsely report zone
            # closed; leave an error margin of 60 seconds before
            # closing a zone.
            if (zoneInfo['status'] == 'closed' and
                zoneInfo['closedSeconds'] < 60):
                logging.debug("ignoring zone status dump state "
                              "change under 60 seconds: " + logMessage)
            else:
                # update zone state
                logging.info("zone state change: " + logMessage)
                ALARMSTATE['zone'][zoneNumber].update(zoneInfo)

    # convert a zone dump into something humans can make sense of
    def convertZoneDump(self, theString):
        logging.debug("converting zone dump, raw string='%s'" % theString)
        returnItems = []

        # every four characters
        inputItems = re.findall('....', theString)
        for inputItem in inputItems:
            # Swap the couples of every four bytes
            # (little endian to big endian)
            swappedBytes = []
            swappedBytes.insert(0, inputItem[0:2])
            swappedBytes.insert(0, inputItem[2:4])

            # add swapped set of four bytes to our return items
            itemHexString = ''.join(swappedBytes)
            # convert from hex to int
            itemInt = int(itemHexString, 16)

            # each value is a timer for a zone that ticks down every
            # five seconds from maxint
            maxTicks = 65536
            itemTicks = maxTicks - itemInt
            itemSeconds = itemTicks * 5

            itemLastClosed = self.humanTimeAgo(timedelta(seconds=itemSeconds))
            status = ''

            if itemHexString == "FFFF":
                itemLastClosed = "Currently Open"
                itemSeconds = 0
                status = 'open'
            elif itemHexString == "0000":
                itemLastClosed = "Last Closed longer ago than I can remember"
                status = 'closed'
            else:
                itemLastClosed = "Last Closed " + itemLastClosed
                status = 'closed'

            logging.debug("zone dump: index=%d raw='%s' swapped='%s' int=%d" %
                          (len(returnItems), inputItem, itemHexString, itemInt))

            returnItems.append({'message': itemLastClosed, 'status': status,
                                'closedSeconds': itemSeconds})
        return returnItems

    # public domain from https://pypi.python.org/pypi/ago/0.0.6
    def delta2dict(self, delta):
        delta = abs(delta)
        return {
            'year':   int(delta.days / 365),
            'day':    int(delta.days % 365),
            'hour':   int(delta.seconds / 3600),
            'minute': int(delta.seconds / 60) % 60,
            'second': delta.seconds % 60,
            'microsecond': delta.microseconds
        }

    def humanTimeAgo(self, dt, precision=3, past_tense='{} ago', future_tense='in {}'):
        """Accept a datetime or timedelta, return a human readable delta string"""
        delta = dt
        if type(dt) is not type(timedelta()):
            delta = datetime.now() - dt

        the_tense = past_tense
        if delta < timedelta(0):
            the_tense = future_tense

        d = self.delta2dict(delta)
        hlist = []
        count = 0
        units = ('year', 'day', 'hour', 'minute', 'second', 'microsecond')
        for unit in units:
            if count >= precision: break     # met precision
            if d[unit] == 0: continue        # skip 0's
            s = '' if d[unit] == 1 else 's'  # handle plurals
            hlist.append('%s %s%s' % (d[unit], unit, s))
            count += 1
        human_delta = ', '.join(hlist)
        return the_tense.format(human_delta)


class AlarmServer(Resource):
    def __init__(self, config):
        Resource.__init__(self)

        self._triggerid = reactor.addSystemEventTrigger('before', 'shutdown',
                                                        self.shutdownEvent)

        # Create Envisalink client connection
        self._envisalinkClientFactory = EnvisalinkClientFactory(config)
        self._envisaconnect = reactor.connectTCP(config.ENVISALINKHOST,
                                                 config.ENVISALINKPORT,
                                                 self._envisalinkClientFactory)

        # Store config
        self._config = config

    def shutdownEvent(self):
        global shuttingdown
        shuttingdown = True
        logging.debug("Disconnecting from Envisalink...")
        self._envisaconnect.disconnect()

    def getChild(self, name, request):
        return self


def usage():
    print 'Usage: ' + sys.argv[0] + ' -c <configfile>'


def main(argv):
    try:
        opts, args = getopt.getopt(argv, "hc:", ["help", "config="])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        elif opt in ("-c", "--config"):
            global conffile
            conffile = arg


if __name__ == "__main__":
    conffile = 'alarmserver.cfg'
    main(sys.argv[1:])

    print('Using configuration file %s' % conffile)
    config = AlarmServerConfig(conffile)
    loggingconfig = {
        'level': config.LOGLEVEL,
        'format': '%(asctime)s %(levelname)s <%(name)s %(module)s %(funcName)s> %(message)s',
        'datefmt': '%Y-%m-%d %H:%M:%S'}
    if config.LOGFILE != '':
        loggingconfig['filename'] = config.LOGFILE
    logging.basicConfig(**loggingconfig)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    logging.info('AlarmServer Starting')
    logging.info('Tested on a Honeywell Vista 20p + EVL-4')

    # allow Twisted to hook into our logging
    observer = log.PythonLoggingObserver()
    observer.start()

    config.initialize_alarmstate()
    AlarmServer(config)

    try:
        reactor.run()
    except KeyboardInterrupt:
        print "Crtl+C pressed. Shutting down."
        logging.info('Shutting down from Ctrl+C')
        sys.exit()
