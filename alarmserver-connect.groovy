/*
 *  Ademco Alarm Panel integration via REST API callbacks
 *
 *  Author: Kent Holloway <drizit@gmail.com>
 *  Modified by: Mike Jahr <michaelj@gmail.com>
 */

definition(
    name: "AlarmServer Integration",
    namespace: "mjahr",
    author: "Mike Jahr <michaelj@gmail.com>",
    description: "Alarmserver Integration App",
    category: "My Apps",
    iconUrl: "https://dl.dropboxusercontent.com/u/2760581/dscpanel_small.png",
    iconX2Url: "https://dl.dropboxusercontent.com/u/2760581/dscpanel_large.png",
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

private def keypadDni()       { return "ademcoKeypad" }
private def getKeypadDevice() {
  def d = getChildDevice(keypadDni())
  if (d == null) {
    log.info("Creating keypad device")
    def initialState = ["message":"Uninitialized"]
    d = addChildDevice(app.namespace, "Ademco Keypad", keypadDni(), null, initialState)
  }
  return d
}

def initialize() {
  log.info("Initializing Ademco integration")
  getKeypadDevice()
}

private updateZones() {
  log.debug "request.JSON: " + request.JSON
  state.zones = request.JSON
  def keypadDevice = getKeypadDevice()
  log.debug "sending zone update to ${keypadDevice.name}"
  for (e in request.JSON) {
    def zoneNumber = e.key
    def zoneStateMap = e.value
    def name = zoneStateMap?.name
    def status = zoneStateMap?.status
    def message = zoneStateMap?.message
    log.info "updateZones: $zoneNumber '$name' is $status: $message"
    keypadDevice.sendEvent([name: "${name}", value: "${status}",
			    descriptionText: "${message}"])
  }
}

private updatePartition() {
  def partition = params.partition
  def message = request.JSON?.message
  log.info "updatePartition: '$message'"
  log.debug "request.JSON: " + request.JSON

  def keypadDevice = getKeypadDevice()
  log.debug "sending partition update to ${keypadDevice.name}"
  for (e in request.JSON) {
    keypadDevice.sendEvent([name: e.key, value: e.value])
  }
  //keypadDevice.sendEvent([name: "message", value: "${message}"])
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

private sendMessage(msg) {
    def newMsg = "Alarm Notification: $msg"
    if (phone1) {
        sendSms(phone1, newMsg)
    }
    if (sendPush == "Yes") {
        sendPush(newMsg)
    }
}
