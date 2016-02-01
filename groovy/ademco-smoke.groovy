/*
 *  Ademco Smoke Sensor
 *
 *  Smoke sensor used by ademco alarm system integration.  Managed as a
 *  child device by ademco-connect.groovy.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 *  Date: 2015-12-15
 */

metadata {
  definition (
    name: "Ademco Smoke Sensor",
    namespace: "mjahr",
    author: "michaelj@gmail.com") {
    capability "Sensor"
    capability "Smoke Detector"  // provides device.smoke
  }

  tiles {
    // Main Row
    standardTile("smoke", "device.smoke", width: 2, height: 2,
		 canChangeBackground: true, canChangeIcon: true) {
      state "clear",  label: 'clear',  icon: "st.alarm.smoke.clear", backgroundColor: "#ffffff"
      state "smoke",  label: 'smoke',  icon: "st.alarm.smoke.smoke", backgroundColor: "#e86d13"
    }

    // This tile will be the tile that is displayed on the Hub page.
    main "smoke"

    // These tiles will be displayed when clicked on the device, in
    // the order listed here.
    details(["smoke"])
  }
}

def setState(String state) {
  // map open/closed to smoke/clear
  def description
  if (state == "open") {
    state = "smoke"
    description = "Smoke detected."
  } else if (state == "closed") {
    state = "clear"
    description = "Smoke is clear."
  } else {
    description = "Unexpected state for smoke sensor: $state"
    log.error(description)
  }
  sendEvent([name: "smoke", value: state, descriptionText: description])
}
