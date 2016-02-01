import json
import logging
import Queue
import requests
import threading
from basePlugin import BasePlugin
from datetime import datetime
from datetime import timedelta
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
        # post updates less frequently when nothing has changed.
        self._REPEAT_UPDATE_INTERVAL  = self.read_config_var(
            'smartthings', 'repeat_update_interval', 55, 'int')

        #  URL example: ${url_base}/${app_id}/update?access_token=${token}
        self._urlbase = self._CALLBACKURL_BASE + "/" + self._CALLBACKURL_APP_ID
        logging.info("SmartThings url: %s" % self._urlbase)

        # keep track of the last update posted so we can skip
        # duplicate posts
        self._last_update_payload = ""
        self._last_update_time = datetime.min

        # set up a queue and thread to send api request asynchronously
        self._is_exiting = threading.Event()
        self._queue = Queue.Queue(self._QUEUE_SIZE)
        self._api_thread = threading.Thread(
            target=self._runApiThread, name="SmartThings api thread")
        self._api_thread.start()

        self._shutdowntriggerid = reactor.addSystemEventTrigger(
            'before', 'shutdown', self._shutdownEventHandler)

    # Sends a regular polling update to SmartThings.
    def sendUpdate(self, statusMap):
        self.sendApiRequest("update", statusMap)

    # TODO: sends an error to SmartThings.
    def sendError(self, errorState):
        message = "Envisalink became unresponsive: %s" % errorState
        # self.postPanelUpdate("ERROR", message, None)

    # Send an api request to SmartThings, asynchronously.
    # path: relative to self._urlbase
    # payload: dict used as body of the post, json-encoded.
    def sendApiRequest(self, path, payload):
        # because we're sending this asynchronously, dump the payload
        # to a string so it's not affected by future updates
        data = json.dumps(payload)

        # if the queue is full, pull off the oldest item to make
        # space for the newer item.
        if self._queue.full():
            logging.warning("Queue is full, dropping one item, size=%d",
                            self._queue.qsize())
            try:
                self._queue.get(block=False)
            except Queue.Empty as e:
                # shouldn't get here except in some extreme race condition
                pass

        try:
            self._queue.put([path, data], block=False)
            logging.debug("Enqueued smartthings api request to /%s", path)
        except Queue.Full as e:
            logging.error("SmartThings api request failed: queue is full; "
                          "qsize=%d path=%s payload=%s",
                          self._queue.qsize(), path, payload)
    ####
    # Methods used by the api thread

    # Callback which runs before shutdown: signal the api thread to exit.
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
                # wake up once per second
                [path, payload] = self._queue.get(block=True, timeout=1)
                # only post if not empty
                if path:
                    self._postApiSynchronous(path, payload)
                self._queue.task_done()
            except Queue.Empty as e:
                pass
        logging.info("SmartThings api thread exiting")

    # Sends an api request synchronously, should only run in worker thread.
    def _postApiSynchronous(self, path, payload):
        # suppress identical updates within a specified interval.
        # TODO: when multiple zones are open simultaneously the keypad
        # will cycle between a handful of messages.  We should really
        # store the last N messages within the interval and suppress
        # updates identical to any of them.
        now = datetime.now()
        delta = now - self._last_update_time
        if (delta < timedelta(seconds=self._REPEAT_UPDATE_INTERVAL) and
            payload == self._last_update_payload):
            logging.info("Skipping repeat update at %s seconds", delta)
            return

        try:
            logging.info("Posting smartthings api to /%s", path)
            url = (self._urlbase + "/" + path +
                   "?access_token=" + self._CALLBACKURL_ACCESS_TOKEN)
            response = requests.post(url, data=payload, timeout=self._API_TIMEOUT)
            if response.status_code not in [requests.codes.ok,
                                            requests.codes.created,
                                            requests.codes.accepted]:
                logging.error("Problem posting a smartthings notification; "
                              "url: %s payload: %s status: %d response: %s",
                              url, payload, response.status_code, response.text)
            else:
                logging.debug("Successfully posted smartthings api; "
                              "path=%s payload=%s", path, payload)
                self._last_update_time = now
                self._last_update_payload = payload
        except requests.exceptions.RequestException as e:
            logging.error("Error communicating with smartthings server: " + str(e))
