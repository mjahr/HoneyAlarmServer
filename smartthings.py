import json
import logging
import queue
import threading
from datetime import datetime
from datetime import timedelta
from typing import Dict, Mapping

import requests
from twisted.internet import reactor

from baseConfig import BaseConfig


class SmartThings:
    def __init__(self, config: BaseConfig):
        self._config: BaseConfig = config
        self._CALLBACKURL_BASE: str = self._get_config_str('callbackurl_base')
        self._CALLBACKURL_APP_ID: str = self._get_config_str('callbackurl_app_id')
        self._CALLBACKURL_ACCESS_TOKEN: str = self._get_config_str('callbackurl_access_token')
        # http timeout in seconds for api requests
        self._API_TIMEOUT: int = self._get_config_int('api_timeout', 10)
        # max number of requests to enqueue before dropping them
        self._QUEUE_SIZE: int = self._get_config_int('queue_size', 100)

        #  URL example: ${url_base}/${app_id}/update?access_token=${token}
        self._urlbase: str = self._CALLBACKURL_BASE + "/" + self._CALLBACKURL_APP_ID
        logging.info("SmartThings url: %s", self._urlbase)

        # Track recent payloads and their timestamps so we can avoid
        # sending duplicate updates.  We track the last N updates to
        # handle the case where multiple zones are open so the keypad
        # cycles between several messages.  Dedup updates within the
        # past N seconds.
        self._cache: Dict[str, datetime] = {}
        # Max interval between sending duplicate updates.
        self._REPEAT_UPDATE_INTERVAL = timedelta(
            seconds=self._get_config_int('repeat_update_interval', 55))

        # set up a queue and thread to send api request asynchronously
        self._is_exiting = threading.Event()
        self._queue: queue.Queue = queue.Queue(self._QUEUE_SIZE)
        self._api_thread = threading.Thread(
            target=self._run_api_thread, name="SmartThings api thread")
        self._api_thread.start()

        self._shutdowntriggerid = reactor.addSystemEventTrigger(
            'before', 'shutdown', self._shutdown_event_handler)

    # Sends a regular polling update to SmartThings.
    def send_update(self, alarmserver_state: Mapping):
        self.send_api_request("update", alarmserver_state)

    # TODO: send an error to SmartThings.
    def send_error(self, error_state: str):
        # message = "Envisalink became unresponsive: %s" % error_state
        # self.postPanelUpdate("ERROR", message, None)
        pass

    # Send an api request to SmartThings, asynchronously.
    # path: relative to self._urlbase
    # payload: dict used as body of the post, json-encoded.
    def send_api_request(self, path: str, payload):
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
            except queue.Empty:
                # shouldn't get here except in some extreme race condition
                pass

        try:
            self._queue.put([path, data], block=False)
            logging.debug("Enqueued smartthings api request to /%s", path)
        except queue.Full:
            logging.error("SmartThings api request failed: queue is full; "
                          "qsize=%d path=%s payload=%s",
                          self._queue.qsize(), path, payload)

    def _get_config_int(self, variable: str, default: int) -> int:
        return self._config.get_int('smartthings', variable, default)

    # read smartthings config var
    def _get_config_str(self, varname: str) -> str:
        return self._config.get_str('smartthings', varname, 'not_provided')

    ####
    # Methods used by the api thread
    # TODO: encapsulate api thread as an object

    # Add a payload to the cache, removing the oldest item if necessary.
    def _add_to_cache(self, payload: str, timestamp: datetime):
        # remove items older than the update interval
        if payload not in self._cache:
            self._cache = {k: v for k, v in self._cache.items()
                           if timestamp - v < self._REPEAT_UPDATE_INTERVAL}

        # add or update timestamp for the current payload
        self._cache[payload] = timestamp
        logging.debug("payload cache size is %d", len(self._cache))

    # Callback which runs before shutdown: signal the api thread to exit.
    def _shutdown_event_handler(self):
        logging.info("Shutting down SmartThings api thread")
        # set the is_exiting event so the loop will exit
        self._is_exiting.set()
        # put an empty item on the queue to wake up the thread if necessary
        self._queue.put(["", ""])

    # Main loop for worker thread: loop forever, pulling requests off the queue.
    def _run_api_thread(self):
        logging.info("SmartThings api thread starting")
        while not self._is_exiting.is_set():
            try:
                # wake up once per second
                [path, payload] = self._queue.get(block=True, timeout=1)
                # only post if not empty
                if path:
                    self._post_api_synchronous(path, payload)
                self._queue.task_done()
            except queue.Empty:
                pass
        logging.info("SmartThings api thread exiting")

    # Sends an api request synchronously, should only run in worker thread.
    def _post_api_synchronous(self, path: str, payload: str):
        # suppress identical updates within a specified interval.
        now = datetime.now()
        update_delta = now - self._cache.get(payload, datetime.min)
        if update_delta < self._REPEAT_UPDATE_INTERVAL:
            logging.debug("Skipping repeat update at %s seconds", update_delta)
            return

        try:
            logging.debug("Posting smartthings api to /%s", path)
            url = (self._urlbase + "/" + path +
                   "?access_token=" + self._CALLBACKURL_ACCESS_TOKEN)
            response = requests.post(url, data=payload, timeout=self._API_TIMEOUT)
            if response.status_code not in [requests.codes.ok,
                                            requests.codes.created,
                                            requests.codes.accepted]:
                logging.error("Problem posting a smartthings notification; "
                              "url: %s status: %d response: %s",
                              url, response.status_code, response.text)
            else:
                logging.debug("Successfully posted smartthings api; "
                              "path=%s payload=%s", path, payload)
                self._add_to_cache(payload, now)
        except requests.exceptions.RequestException as err:
            logging.error("Error communicating with smartthings server: %s", str(err))
