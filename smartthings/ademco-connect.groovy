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
  page(name: "zones", title: "Zones", content: "zonePage",
       uninstall: true, install: true)
  // TODO: create a panel instead of selecting it
  // section("Alarm Panel:") {
  //   input "paneldevice", "capability.alarm", title: "Alarm Panel (required)", multiple: false, required: false
  // }
  // section("Keypad:") {
  //   input "keypaddevice", "capability.sensor", title: "Keypad Device (required)", multiple: false, required: false
  // }
  // section("Notifications (optional) - NOT WORKING:") {
  //   input "sendPush", "enum", title: "Push Notification", required: false,
  //     metadata: [
  //      values: ["Yes","No"]
  //     ]
  //   input "phone1", "phone", title: "Phone Number", required: false
  // }
  // section("Notification events (optional):") {
  //   input "notifyEvents", "enum", title: "Which Events?", description: "default (none)", required: false, multiple: false,
  //    options:
  //     ['all','alarm','closed','open','closed','partitionready',
  //      'partitionnotready','partitionarmed','partitionalarm',
  //      'partitionexitdelay','partitionentrydelay'
  //     ]
  // }
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

def zonePage() {
  log.debug("zonePage()")
  def zoneNames = [:]
  for (e in state.zones) {
    zoneNames[e.key] = e.value?.name
  }

  return dynamicPage(name: "zones", title: "Select zones", uninstall:true) {
    section("Contact sensors") {
      paragraph("Select zones to create contact sensors for:")
      input(name: "contacts", title: "", type: "enum", required: true,
	    multiple: true, description: "Tap to choose",
	    metadata: [values: zoneNames])
    }
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

// Keypad device is a child device which displays the alarm system status.
private def getKeypadDevice() {
  def d = getChildDevice(keypadDni())
  if (d == null) {
    log.info("Creating keypad device")
    def initialState = ["message": "Uninitialized"]
    d = addChildDevice(app.namespace, "Ademco Keypad", keypadDni(), null, initialState)
  }
  return d
}

private def getPanelDevice() {
  def d = getChildDevice(panelDni())
  if (d == null) {
    log.info("Creating panel device")
    def initialState = ["status": "Uninitialized"]
    d = addChildDevice(app.namespace, "Ademco Panel", panelDni(), null, initialState)
  }
  return d
}


// Identifiers used for the keypad and panel devices.
private def keypadDni() { return "ademcoKeypad" }
private def panelDni()  { return "ademcoPanel"  }

private def getZoneDevice(zoneNumber) {

}

def initialize() {
  log.info("Initializing Ademco integration")
  getKeypadDevice()
  getPanelDevice()
}

private updateZones() {
  log.debug "request.JSON: " + request.JSON
  state.zones = request.JSON
  def panelDevice = getPanelDevice()
  log.debug "sending zone update to ${panelDevice.name}"
  for (e in request.JSON) {
    def zoneNumber = e.key
    def zoneStateMap = e.value
    def name = zoneStateMap?.name
    def status = zoneStateMap?.status
    def message = zoneStateMap?.message
    log.info "updateZones: $zoneNumber '$name' is $status: $message"
    panelDevice.sendEvent([name: "${name}", value: "${status}",
			    descriptionText: "${name}: ${message}"])
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
    sendEvent(paneldevice, name: "alarm", value: "${status}")
  }
}

private updatePanel() {
  def message = request.JSON?.message
  log.info "updatePanel: $message"
}
