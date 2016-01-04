/*
 *  Ademco Panel
 *
 *  Panel is a conduit for all updates from the alarmserver.
 *  It doesn't do anything itself.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 *  Date: 2015-12-15
 */

metadata {
  definition (name: "Ademco Panel", author: "Mike Jahr <michaelj@gmail.com>") {
    capability "Sensor"
  }

  tiles {
    standardTile("partition", "device.partition", width: 1, height: 1,
                 canChangeBackground: true, canChangeIcon: true) {
      state "armed",     label: 'Armed',      backgroundColor: "#79b821", icon:"st.Home.home3"
      state "exitdelay", label: 'ExitDelay',  backgroundColor: "#ff9900", icon:"st.Home.home3"
      state "entrydelay",label: 'EntryDelay', backgroundColor: "#ff9900", icon:"st.Home.home3"
      state "notready",  label: 'Open',       backgroundColor: "#ffcc00", icon:"st.Home.home2"
      state "ready",     label: 'Ready',      backgroundColor: "#79b821", icon:"st.Home.home2"
      state "alarm",     label: 'Alarm',      backgroundColor: "#ff0000", icon:"st.Home.home3"
    }

 	main "partition"

    // These tiles will be displayed when clicked on the device, in the order listed here.
    details(["partition"])
  }
}
