/*
 *  Ademco Keypad
 *
 *  Displays alarm system status.
 *
 *  Author: Mike Jahr <michaelj@gmail.com>
 *  Date: 2015-12-15
 */

metadata {
  definition (
    name: "Ademco Keypad",
    namespace: "mjahr",
    author: "Mike Jahr <michaelj@gmail.com>") {
    capability "Sensor"
  }

  tiles {
    standardTile("keypad", "device.message", width: 2, height: 1,
                 canChangeBackground: true, canChangeIcon: true) {
    }

    main "keypad"

    // These tiles will be displayed when clicked on the device, in the order listed here.
    details(["keypad"])
  }
}
