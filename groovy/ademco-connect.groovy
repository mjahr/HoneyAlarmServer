/*
 *  Ademco Alarm Panel integration via REST API callbacks
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

preferences {
  page(name: "zones", title: "Zones", content: "zonePage")
}

mappings {
  // polling state update for partitions and zones
  path("/update") {
    action: [ POST: "update" ]
  }
}

// Pref page that allows selecting a device type for each zone.
def zonePage() {
  log.debug("zonePage()")
  def zoneTypes = [ "" : "None",
                    "Ademco Door Sensor"   : "Door Sensor",
                    "Ademco Motion Sensor" : "Motion Sensor",
                    "Ademco Smoke Sensor"  : "Smoke Sensor" ]

  return dynamicPage(name: "zones", title: "Select zones") {
    log.debug("building zonePage dynamicPage")
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
    log.debug("done with zonePage dynamicPage")
  }
}

def installed() {
  log.debug "Installed!"
  initialize()
}

def updated() {
  log.debug "Updated!"
  initialize()
}

def uninstalled() {
  log.debug "Uninstalled!  Deleting child devices."
  getChildDevices().each { deleteChildDevice(it) }
}

// Keypad device is a child device which displays the alarm system status.
private def getKeypadDevice() { return getChildDevice(keypadDni()) }
private def getPanelDevice()  { return getChildDevice(panelDni())  }
private def getZoneDevice(zoneNumber) {
  return getChildDevice(zoneDeviceDni(zoneNumber))
}

// Identifiers used for child devices.
private def keypadDni() { return "ademcoKeypad" }
private def panelDni()  { return "ademcoPanel"  }
private def zoneDeviceDni(zoneNumber) {
  return "ademcoZone" + zoneNumber
}

// Extracts keys from a map and sorts by number.
def getOrderedKeyList(Map map) {
  return map.keySet().collect { it as int }.sort().collect { it as String }
}
// For some reason I can't call getOrderedKeyList(state.zones).
def getOrderedStateZones() {
  return state.zones.keySet().collect { it as int }.sort().collect { it as String }
}

// Initialize takes user-specified preferences and creates child
// devices as appropriate.
def initialize() {
  log.info("Initializing child devices for Ademco integration")

  if (getKeypadDevice() == null) {
    log.info("Creating keypad device")
    def initialState = [ "message": "Uninitialized" ]
    addChildDevice(app.namespace, "Ademco Keypad", keypadDni(), null, initialState)
  }
  log.info("deleting panel device")
  deleteChildDevice(panelDni())
  // if (getPanelDevice() == null) {
  //   log.info("Creating panel device")
  //   def initialState = [ "status": "Uninitialized" ]
  //   addChildDevice(app.namespace, "Ademco Panel", panelDni(), null, initialState)
  // }

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

// Polling update
private update() {
  state.lastUpdate = request.JSON
  updateZoneState(request.JSON?.zone)
  def partitionMap = request.JSON?.partition
  for (partitionNumber in getOrderedKeyList(partitionMap)) {
    updatePartitionState(partitionNumber, partitionMap[partitionNumber])
  }
}

private updateZoneState(Map zoneStateMap) {
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
      log.debug "updateZones: no device for zone $zoneNumber '$name' is $status: $message"
      keypadDevice.sendEvent([name: "${name}", value: "${status}", displayed: false,
			      descriptionText: "${name}: ${message}"])
    }
  }
}

private updatePartitionState(String partition, Map partitionStateMap) {
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
