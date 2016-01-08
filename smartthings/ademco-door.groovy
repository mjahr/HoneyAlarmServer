/*
 *  Ademco Door Sensor
 *
 *  Door sensor used by ademco alarm system integration.  Managed as a
 *  child device by ademco-connect.groovy.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 *  Date: 2015-12-15
 */

metadata {
  definition (
    name: "Ademco Door Sensor",
    namespace: "mjahr",
    author: "Mike Jahr <michaelj@gmail.com>") {
    capability "Contact Sensor"  // provides device.contact
    capability "Sensor"
  }

  tiles {
    multiAttributeTile(name:"contact", type: "generic", width: 6, height: 4) {
      tileAttribute("device.contact", key: "PRIMARY_CONTROL") {
        attributeState("open",   label:'${name}', icon:"st.contact.contact.open",
                       backgroundColor:"#ffa81e")
        attributeState("closed", label:'${name}', icon:"st.contact.contact.closed",
                       backgroundColor:"#79b821")
      }
    }

    main "contact"

    // These tiles will be displayed when clicked on the device, in
    // the order listed here.
    details(["contact"])
  }
}

def setState(String state) {
  sendEvent([name: "contact", value: state,
             descriptionText: "Door is ${state}."])
}
