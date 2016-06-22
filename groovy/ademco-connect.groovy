/*
 *  Ademco Alarm Panel integration via REST API updates.  This
 *  SmartApp listens for updates sent by the SmartAlarmServer python
 *  script.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 */

definition(
    name: "Ademco Integration",
    namespace: "mjahr",
    author: "Mike Jahr <michaelj@gmail.com>",
    description: "Ademco Integration App",
    category: "My Apps",
    oauth: true
)

import groovy.json.JsonBuilder

mappings {
  // Endpoint called by SmartAlarmServer to update state for
  // partitions and zones.
  path("/update") {
    action: [ POST: "receiveUpdate" ]
  }
}

preferences {
  page(name: "zones", title: "Zones", content: "zonePage")
}

// Pref page that allows selecting a device type for each zone.
def zonePage() {
  log.debug("Creating zone prefs page")
  def zoneTypes = [ "" : "None",
                    "Ademco Door Sensor"   : "Door Sensor",
                    "Ademco Motion Sensor" : "Motion Sensor",
                    "Ademco Smoke Sensor"  : "Smoke Sensor" ]

  return dynamicPage(name: "zones", title: "Select zones") {
    section("Zone sensors") {
      paragraph("Select zones to create sensors for:")
      for (zoneNumber in getOrderedStateZones()) {
        def zoneStateMap = state.zones[zoneNumber]
        def zoneName = zoneStateMap.get("name", "zone " + zoneNumber)
        def zoneDni = zoneDeviceDni(zoneNumber)
	def zoneTitle = "${zoneNumber}: ${zoneName}"
        input(name: zoneDni, title: zoneTitle, type: "enum", required: false,
              multiple: false, description: zoneTitle,
              metadata: [values: zoneTypes])
      }
    }
  }
}

def installed() {
  log.debug("Installed!")
  initialize()
}

def updated() {
  log.debug("Updated!")
  unschedule()
  initialize()
}

def uninstalled() {
  log.debug("Uninstalled!  Deleting child devices.")
  getChildDevices().each { deleteChildDevice(it) }
  unschedule()
}

// Keypad device is a child device which displays the alarm system status.
def getKeypadDevice() { return getChildDevice(keypadDni()) }
def getZoneDevice(zoneNumber) {
  return getChildDevice(zoneDeviceDni(zoneNumber))
}

// Identifiers used for child devices.
def keypadDni() { return "ademcoKeypad" }
def zoneDeviceDni(zoneNumber) {
  return "ademcoZone" + zoneNumber
}

// Extracts keys from a map and sorts by number.
def getOrderedKeyList(Map map) {
  return map.keySet().collect { it as int }.sort().collect { it as String }
}
// For some reason I can't call getOrderedKeyList(state.zones), so
// this method is a workaround.
def getOrderedStateZones() {
  return state.zones.keySet().collect { it as int }.sort().collect { it as String }
}

// Initialize takes user-specified preferences and creates child
// devices as appropriate.
def initialize() {
  // Check for timeout every 5 minutes.
  log.info("Scheduling timeout check to run every 5 minutes.")
  unschedule()
  runEvery5Minutes(checkForTimeout)

  log.info("Initializing child devices for Ademco integration")

  if (getKeypadDevice() == null) {
    log.info("Creating keypad device")
    def initialState = [ "message": "Uninitialized" ]
    addChildDevice(app.namespace, "Ademco Keypad", keypadDni(), null, initialState)
  }

  for (zoneNumber in getOrderedStateZones()) {
    // Get preference for each zone.
    def zoneDni = zoneDeviceDni(zoneNumber)
    def d = getChildDevice(zoneDni)
    def deviceType = this.settings[zoneDni]
    if (deviceType == null || deviceType == "") {
      if (d != null) {
        log.info("Deleting child device for zone $zoneNumber")
        deleteChildDevice(zoneDni)
      }
    } else if (d == null) {
        log.info("Adding child device for zone $zoneNumber: $deviceType")
        d = addChildDevice(app.namespace, deviceType, zoneDni, null,
			   state.zones[zoneNumber])
    } else {
      log.info("Keeping child device for zone $zoneNumber: $deviceType")
    }
  }
}

// Scheduled to run every 5 minutes.  Verifies that the most recent
// update is not too long ago, and posts a notification otherwise.
def checkForTimeout() {
  def now = now()
  def lastUpdate = state.lastUpdateTimestamp ? state.lastUpdateTimestamp : 0
  // compute time from last update to now
  def updateMs = now - lastUpdate
  def updateHours = updateMs / 1000.0 / 60.0 / 60.0
  def updateTimeStr = formatTimeDelta(updateMs)
  log.debug("Timeout check: last update was ${updateTimeStr} ago")

  // Timeout after 15 minutes
  if (updateHours > 0.25) {
    // compute time from last update to last notification; will be
    // negative if we haven't notified since receiving the last
    // update.
    def lastNotify = state.lastTimeoutNotifyTimestamp ? state.lastTimeoutNotifyTimestamp : 0
    def notifyMs = lastNotify - lastUpdate
    def notifyHours = notifyMs / 1000.0 / 60.0 / 60.0

    // send a push after 15 minutes, and then once per hour
    if ((int) notifyHours < (int) updateHours) {
      sendPush("Ademco alarmserver is offline; last update was ${updateTimeStr} ago")
      state.lastTimeoutNotifyTimestamp = now
    }
  }
}

// Returns a time delta rounded to the nearest minute.
def formatTimeDelta(long ms) {
  def seconds = (int) Math.round(ms / 1000.0)
  def minutes = (int) Math.round(seconds / 60.0)
  def hours = (int) (minutes / 60)  // truncate instead of rounding
  if (seconds < 60) {
    return sprintf("%d seconds", seconds)
  } else if (minutes < 60) {
    return sprintf("%d minutes", minutes)
  } else {
    return sprintf("%d hours %d minutes", hours, minutes)
  }
}

// Endpoint called by alarmserver
def receiveUpdate() {
  // notify if this is the first update since a timeout.
  def now = now()
  def timeStr = formatTimeDelta(now - state.lastUpdateTimestamp)
  log.debug("Received update; last update was ${timeStr} ago")
  if (state.lastUpdateTimestamp < state.lastTimeoutNotifyTimestamp) {
    sendPush("Ademco alarmserver is back online; last update was ${timeStr} ago")
  }

  state.lastUpdateTimestamp = now
  state.lastUpdate = request.JSON
  updateZoneState(request.JSON?.zone)
  def partitionMap = request.JSON?.partition
  for (partitionNumber in getOrderedKeyList(partitionMap)) {
    updatePartitionState(partitionNumber, partitionMap[partitionNumber])
  }
}

def updateZoneState(Map zoneStateMap) {
  state.zones = zoneStateMap
  def keypadDevice = getKeypadDevice()
  for (zoneNumber in getOrderedKeyList(zoneStateMap)) {
    def zoneState = zoneStateMap[zoneNumber]
    def name = zoneState?.name
    def status = zoneState?.status
    def message = zoneState?.message
    def zoneDevice = getZoneDevice(zoneNumber)
    if (zoneDevice) {
      log.debug "updateZone: ${zoneDevice} is ${status}"
      zoneDevice.setState(status)
    } else {
      // If there's no device for this zone, update the state on the
      // keypad but don't display it in the activity feed.
      log.debug("updateZones: no device for zone $zoneNumber '$name' " +
		"is $status: $message")
      keypadDevice.sendEvent(
	[name: "${name}", value: "${status}", displayed: false,
	 descriptionText: "${name}: ${message}"])
    }
  }
}

def updatePartitionState(String partition, Map partitionStateMap) {
  // Add every field from the partition state as an event.  SmartThings
  // will dedup events where necessary.
  def keypadDevice = getKeypadDevice()
  log.debug "sending partition state update to ${keypadDevice.name}"
  for (e in partitionStateMap) {
    if (e.key == "message") {
      // Messages are special: display them in the activity feed.
      keypadDevice.sendEvent([name: e.key, value: e.value,
                              descriptionText: e.value])
    } else {
      // For every other variable, update the state on the keypad but
      // do not display in activity feed.
      keypadDevice.sendEvent([name: e.key, value: e.value, displayed: false,
			      descriptionText: "${e.key} is ${e.value}"])
    }
  }
}
