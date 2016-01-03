import json
import logging
import Queue
import requests
import threading
from basePlugin import BasePlugin
#from threading import Event
from twisted.internet import reactor

class SmartthingsPlugin(BasePlugin):
    # read smartthings config var
    def read_st_config_var(self, varname):
        return self.read_config_var('smartthings', varname, 'not_provided', 'str')

    def __init__(self, configfile):
        # call ancestor for common setup
        super(SmartthingsPlugin, self).__init__(configfile)

        self._CALLBACKURL_BASE         = self.read_st_config_var('callbackurl_base')
        self._CALLBACKURL_APP_ID       = self.read_st_config_var('callbackurl_app_id')
        self._CALLBACKURL_ACCESS_TOKEN = self.read_st_config_var('callbackurl_access_token')
        self._CALLBACKURL_EVENT_CODES  = self.read_st_config_var('callbackurl_event_codes')
        # http timeout in seconds for api requests
        self._API_TIMEOUT = self.read_config_var(
            'smartthings', 'api_timeout', 10, 'int')
        # max number of requests to enqueue before dropping them
        self._QUEUE_SIZE  = self.read_config_var(
            'smartthings', 'queue_size', 100, 'int')

        #  URL example: ${callbackurl_base}/${callbackurl_app_id}/panel/${code}/${zoneorpartitionnumber}?access_token=${callbackurl_access_token}
        self._urlbase = self._CALLBACKURL_BASE + "/" + self._CALLBACKURL_APP_ID
        logging.info("SmartThings url: %s" % self._urlbase)

        # set up a queue and thread to send api request asynchronously
        self._is_exiting = threading.Event()
        self._queue = Queue.Queue(self._QUEUE_SIZE)
        self._api_thread = threading.Thread(
            target=self._runApiThread, name="SmartThings api thread")
        self._api_thread.start()

        self._shutdowntriggerid = reactor.addSystemEventTrigger(
            'before', 'shutdown', self._shutdownEventHandler)

    def armedAway(self, user):
        message = "Security system armed away by " + user
        self.postPanelUpdate("ARMED_AWAY", message, user)

    def armedHome(self, user):
        message = "Security system armed home by " + user
        self.postPanelUpdate("ARMED_HOME", message, user)

    def disarmedAway(self, user):
        message = "Security system disarmed from away status by " + user
        self.postPanelUpdate("DISARMED_AWAY", message, user)

    def disarmedHome(self, user):
        message = "Security system disarmed from home status by " + user
        self.postPanelUpdate("DISARMED_AWAY", message, user)

    def envisalinkUnresponsive(self, condition):
        message = "Envisalink became unresponsive: %s" % condition
        self.postPanelUpdate("ERROR", message, None)

    def postPanelUpdate(self, status, message, user):
        payload = { 'message': message, 'status': status }
        if user is not None:
            payload['user'] = user
        self.sendApiRequest("panel", payload)

    def alarmTriggered(self, alarmDescription, zone, zoneName):
        self.postAlarm("IN_ALARM", alarmDescription, zone, zoneName)

    def alarmCleared(self, alarmDescription, zone, zoneName):
        self.postAlarm("ALARM_IN_MEMORY", alarmDescription, zone, zoneName)

    def postAlarm(self, status, description, zone, zoneName):
        # sensorType = self.getZoneType(zone, status)
        message =  ("Alarm %s in %s: %s" % status, zoneName, description)
        logging.debug(message);
        payload = { 'message': message,
                    'description': description,
                    'zonename': zoneName }
        path = "/".join(str(x) for x in ["alarm", zone, status])
        self.sendApiRequest(path, payload)

    def zoneDump(self, statusMap):
        self.sendApiRequest("zones", statusMap)

    def partitionStatus(self, partition, statusMap):
        path = "/".join(str(x) for x in ["partition", partition])
        self.sendApiRequest(path, statusMap)

    # Send an api request to SmartThings, asynchronously.
    # path: relative to self._urlbase
    # payload: dict used as body of the post, json-encoded.
    def sendApiRequest(self, path, payload):
        try:
            self._queue.put([path, payload], block=False)
        except e:
            logging.error("SmartThings api request failed; queue is full; "
                          "path=%s payload=%s", path, payload)
    ####
    # Methods related to the api thread

    # callback which runs before shutdown: signal the api thread to exit
    def _shutdownEventHandler(self):
        logging.info("Shutting down SmartThings api thread")
        # set the is_exiting event so the loop will exit
        self._is_exiting.set()
        # put an empty item on the queue to wake up the thread if necessary
        self._queue.put(["", ""])

    # Main loop for worker thread: loop forever, pulling requests off the queue.
    def _runApiThread(self):
        logging.info("SmartThings api thread starting")
        while not self._is_exiting.is_set():
            try:
                [path, payload] = self._queue.get(block=True, timeout=1)
                # only post if not empty
                if path:
                    self._postApiSynchronous(path, payload)
            except Exception as e:
                pass
        logging.info("SmartThings api thread exiting")

    # Sends an api request synchronously, should only run in worker thread.
    def _postApiSynchronous(self, path, payload):
        try:
            url = (self._urlbase + "/" + path +
                   "?access_token=" + self._CALLBACKURL_ACCESS_TOKEN)
            response = requests.post(url, json=payload, timeout=self._API_TIMEOUT)
            if response.status_code not in [requests.codes.ok,
                                            requests.codes.created,
                                            requests.codes.accepted]:
                logging.error("Problem sending a smartthings notification, url: "
                              "%s payload: %s status: %d response: %s" %
                              (url, payload, response.status_code, response.text))
        except requests.exceptions.RequestException as e:
            logging.error("Error communicating with smartthings server: " + str(e))
