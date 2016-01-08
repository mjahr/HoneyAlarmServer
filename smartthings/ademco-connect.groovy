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
  // regular polling update for zones, as well as zone state changes
  path("/zones") {
    action: [ POST: "updateZones" ]
  }
  // updates for partition state change and keypad updates
  path("/partition/:partition") {
    action: [ POST: "updatePartition" ]
  }
  // alarms, arm/disarm, and other real-time updates
  path("/panel") {
    action: [ POST: "updatePanel" ]
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

// Extracts keys from a zone map and sorts by number.
def getOrderedZoneList(Map zoneMap) {
  return zoneMap.keySet().collect { it as int }.sort().collect { it as String }
}
// For some reason I can't call getOrderedZoneList(state.zones).
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
  if (getPanelDevice() == null) {
    log.info("Creating panel device")
    def initialState = [ "status": "Uninitialized" ]
    addChildDevice(app.namespace, "Ademco Panel", panelDni(), null, initialState)
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

private updateZones() {
  log.debug "request.JSON: " + request.JSON
  state.zones = request.JSON
  def panelDevice = getPanelDevice()
  log.debug "sending zone update to ${panelDevice.name}"

  for (zoneNumber in getOrderedZoneList(request.JSON)) {
    def zoneStateMap = request.JSON[zoneNumber]
    def name = zoneStateMap?.name
    def status = zoneStateMap?.status
    def message = zoneStateMap?.message
    log.info "updateZones: $zoneNumber '$name' is $status: $message"
    panelDevice.sendEvent([name: "${name}", value: "${status}",
                           displayed: false,
                           descriptionText: "${name}: ${message}"])

    def zoneDevice = getZoneDevice(zoneNumber)
    if (zoneDevice) {
      zoneDevice.setState(status)
    }
  }
}

private updatePartition() {
  def partition = params.partition
  def message = request.JSON?.message
  log.info "updatePartition: '$message'"
  log.debug "request.JSON: " + request.JSON

  // Add every field from the json payload as an event.  SmartThings
  // will dedup events where necessary.
  def panelDevice = getPanelDevice()
  log.debug "sending partition update to ${panelDevice.name}"
  for (e in request.JSON) {
    panelDevice.sendEvent([name: e.key, value: e.value, display: false,
                           descriptionText: "${e.key} is ${e.value}"])
    if (e.key == "message") {
      def keypadDevice = getKeypadDevice()
      keypadDevice.sendEvent([name: e.key, value: e.value,
                              descriptionText: e.value])
    }
  }
}

private updateAlarm() {
  def zone = params.zone
  def status = params.status
  def zonename = request.JSON?.zonename
  def message = request.JSON?.message
  log.info "updateAlarm: $zone '$zonename' is $status: $message"
  log.debug "request.JSON: " + request.JSON

  if (paneldevice) {
    sendEvent(paneldevice, name: "alarm", value: "${status}", displayed: false)
  }
}

private updatePanel() {
  def message = request.JSON?.message
  log.info "updatePanel: $message"
}
