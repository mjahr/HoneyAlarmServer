/*
 *  Ademco Motion Sensor
 *
 *  Motion sensor used by ademco alarm system integration.  Managed as a
 *  child device by ademco-connect.groovy.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 *  Date: 2015-12-15
 */

metadata {
  definition (
    name: "Ademco Motion Sensor",
    namespace: "mjahr",
    author: "michaelj@gmail.com") {
    capability "Sensor"
    capability "Motion Sensor"  // provides device.motion
  }

  tiles {
    standardTile("zone", "device.motion", width: 2, height: 2,
                 canChangeBackground: true, canChangeIcon: true) {
      state("active",   label:"motion",    icon:"st.motion.motion.active",   backgroundColor:"#53a7c0")
      state("inactive", label:"no motion", icon:"st.motion.motion.inactive", backgroundColor:"#ffffff")
    }

    // This tile will be the tile that is displayed on the Hub page.
    main "zone"

    // These tiles will be displayed when clicked on the device, in the order listed here.
    details(["zone"])
  }
}

def setState(String state) {
  // map open/closed to motion/no motion
  def description
  def display = true
  if (state == "open") {
    state = "active"
    description = "Motion detected."
  } else if (state == "closed") {
    state = "inactive"
    // Do not display inactive transitions in the activity feed
    // because they always immediately follow active transitions and
    // just add clutter.
    display = false
    description = "No motion detected."
  } else {
    description = "Unexpected state for motion sensor: $state"
    log.error(description)
  }
  sendEvent([name: "motion", value: state, displayed: display,
	     descriptionText: description])
}
