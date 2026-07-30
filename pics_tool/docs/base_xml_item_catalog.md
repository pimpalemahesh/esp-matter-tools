# Base.xml (MCORE) — Full Item Catalog by Type

Spec 1.6 · **132 items**, each listed once under its type.

| Type | Count | How it is decided |
|---|---:|---|
| 1. Input-seeded | 15 | set directly by a profile input |
| 2. Derived (conditional) | 12 | computed from seeds via cond fixpoint |
| 3. Safe default-ON leaves | 23 | standard for any node; default enabled |
| 4. Role/feature-area controlled | 49 | auto on/off from role + bridge/icd/ota flags |
| 5. Manual (product-specific) | 33 | no input/rule; engineer must decide |

## Type 1 — Input-seeded (set directly by a profile input)

Device facts the user answers via `transport` / `ble_commissioning` / `role` / `onboarding` / `ota` (+ `is_bridge` / `is_icd`).

- `MCORE.COM.BLE` — Does the device support communication over Bluetooth Low Energy (BLE) ?
- `MCORE.COM.WIFI_2P4GHZ` — Does the device support communication over 2.4GHz Wi-Fi ?
- `MCORE.COM.WIFI_5GHZ` — Does the device support communication over 5GHz Wi-Fi ?
- `MCORE.COM.ETH` — Does the device support communication over Ethernet ?
- `MCORE.COM.THR` — Does the device support communication over Thread ?
- `MCORE.ROLE.COMMISSIONER` — Does the device implement a Commissioner ?
- `MCORE.ROLE.COMMISSIONEE` — Does the device implement a Commissionee ?
- `MCORE.ROLE.CONTROLLER` — Does the device implement a Controller ?
- `MCORE.DD.MANUAL_PC` — Does the commissionee device or device packaging have a Manual Pairing Code?
- `MCORE.DD.NFC` — Does the commissionee device have a NFC tag containing the onboarding payload?
- `MCORE.DD.11_MANUAL_PC` — Does the commissioner support accepting an 11-digit Manual Pairing Code for commissioning?
- `MCORE.SC.SIT_ICD` — Is the device a Short Idle Time ICD?
- `MCORE.BRIDGE` — Does the DUT implement a Bridge
- `MCORE.OTA.Requestor` — Does the DUT implement the OTA Requestor Device Type?
- `MCORE.OTA.Provider` — Does the DUT implement the OTA Provider Device Type?

## Type 2 — Derived (computed from seeds via cond)

Auto-decided by the cond fixpoint; never asked.

- `MCORE.COM.WIFI` — Does the device support communication over Wi-Fi ?  
  → M if MCORE.COM.WIFI_2P4GHZ; M if MCORE.COM.WIFI_5GHZ
- `MCORE.COM.WIRELESS` — Does the device support Wi-Fi or Thread interfaces communication ?  
  → M if MCORE.COM.WIFI; M if MCORE.COM.THR
- `MCORE.DD.QR` — Does the commissionee device or device packaging have a QR code based onboarding payload?  
  → M if MCORE.DD.CONCATENATED_QR_CODE
- `MCORE.DD.CTRL_CONCATENATED_QR_CODE_2` — Does the Commissioner indicate to the user that devices must be commissioned individually using their separate QR codes or Manual Pairing Codes?  
  → O if NOT (MCORE.DD.CTRL_CONCATENATED_QR_CODE_1)
- `MCORE.DD.DISCOVERY_BLE` — Does the commissioner support Discovery Capability over BLE?  
  → M if MCORE.ROLE.COMMISSIONER AND MCORE.COM.BLE
- `MCORE.DD.DISCOVERY_IP` — Does the commissioner support Discovery Capability over IP Network?  
  → M if MCORE.ROLE.COMMISSIONER
- `MCORE.DD.STANDARD_COMM_FLOW` — Does the DUT support commissioning via Standard Commissioning Flow?  
  → M if MCORE.DD.11_MANUAL_PC
- `MCORE.COM.PAF` — Does the commissioner or the device support Commissioning over Wi-Fi PAF?  
  → M if MCORE.COM.WIFI & MCORE.DD.DISCOVERY_PAF
- `MCORE.BRIDGE.BatInfo` — Does the DUT have information on battery level of (at least some of) of its bridged devices  
  → O if MCORE.BRIDGE
- `MCORE.BRIDGE.OtherControl` — Does the DUT have means to change the state of (at least some of) of its bridged devices, e.g. through a manufacturer-provided app  
  → O if MCORE.BRIDGE
- `MCORE.BRIDGE.AllowDeviceRename` — Does the DUT have means to change the name of (at least some of) of its bridged devices, e.g. through a manufacturer-provided app  
  → O if MCORE.BRIDGE
- `MCORE.OTA.VendorSpecific` — Does the DUT support Vendor specific OTA implementation?  
  → M if MCORE.ROLE.COMMISSIONEE AND NOT (MCORE.OTA.Requestor)

## Type 3 — Safe default-ON leaves (standard for any node)

Enabled by the per-role default profile; standard on virtually every commissionable node.

- `MCORE.DD.COMMISSIONING_SUBTYPE_V` — Does the commissionee device support advertising the Vendor ID Commissioning Subtype in Commissionable Node Discovery through DNS-SD advertisements?
- `MCORE.DD.COMMISSIONING_SUBTYPE_T` — Does the commissionee device support advertising the Device Type Commissioning Subtype in Commissionable Node Discovery through DNS-SD advertisements?
- `MCORE.DD.TXT_KEY_VP` — Does the commissionee device support TXT Key 'VP' (Vendor ID / Product ID) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.DD.TXT_KEY_DT` — Does the commissionee device support TXT Key 'DT' (Device Type) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.DD.TXT_KEY_DN` — Does the commissionee device support TXT Key 'DN' (Device Name) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.DD.TXT_KEY_RI` — Does the commissionee device support TXT Key 'RI' (Rotating Identifier) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.DD.TXT_KEY_PH` — Does the commissionee device support TXT Key 'PH' (Pairing Hint) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.DD.TXT_KEY_PI` — Does the commissionee device support TXT Key 'PI' (Pairing Instruction) in it’s DNS-SD TXT Records for Commissionable Node Discovery?
- `MCORE.SC.VENDOR_SUBTYPE` — Does device support optional subtype _V in commissionable node discovery mDNS?
- `MCORE.SC.DEVTYPE_SUBTYPE` — Does device support optional subtype _T in commissionable node discovery mDNS?
- `MCORE.SC.VP_KEY` — Does device support optional key VP in commissionable node discovery mDNS?
- `MCORE.SC.DT_KEY` — Does device support optional key DT in commissionable node discovery mDNS?
- `MCORE.SC.DN_KEY` — Does device support optional key DN in commissionable node discovery mDNS?
- `MCORE.SC.RI_KEY` — Does device support optional key RI in commissionable node discovery mDNS?
- `MCORE.SC.PH_KEY` — Does device support optional key PH in commissionable node discovery mDNS?
- `MCORE.SC.PI_KEY` — Does device support optional key PI in commissionable node discovery mDNS?
- `MCORE.SC.SII_OP_DISCOVERY_KEY` — Does device support optional key SII in operational discovery mDNS?
- `MCORE.SC.SAI_OP_DISCOVERY_KEY` — Does device support optional key SAI in operational discovery mDNS?
- `MCORE.SC.SAT_OP_DISCOVERY_KEY` — Does device support optional key SAT in operational discovery mDNS?
- `MCORE.SC.T_KEY` — Does device support optional key T in operational discovery mDNS?
- `MCORE.SC.SII_COMM_DISCOVERY_KEY` — Does device support optional key SII in commissionable node discovery mDNS?
- `MCORE.SC.SAI_COMM_DISCOVERY_KEY` — Does device support optional key SAI in commissionable node discovery mDNS?
- `MCORE.IDM.S` — Is the device a Server

## Type 4 — Role / feature-area controlled (auto on/off)

Decided automatically once `role` and the `bridge`/`icd`/`ota` flags are known (role deny-lists + feature-area gates). Grouped by namespace.

### MCORE.ACL (1)
- `MCORE.ACL.Administrator` — Does the DUT have Administer privilege over the Access Control of another node?

### MCORE.BRIDGECLIENT (1)
- `MCORE.BRIDGECLIENT` — Does the DUT support a Bridge

### MCORE.DD (7)
- `MCORE.DD.COMM_DISCOVERY` — Does the DUT support Commissioner Discovery?
- `MCORE.DD.CTRL_CONCATENATED_QR_CODE_1` — Does the commissioner support scanning and processing concatenated QR codes?
- `MCORE.DD.MANUAL_PC_COMMISSIONING` — Does the commissioner support accepting a Manual Pairing Code for commissioning?
- `MCORE.DD.21_MANUAL_PC` — Does the commissioner support accepting a 21-digit Manual Pairing Code for commissioning?
- `MCORE.DD.SCAN_NFC` — Does the commissioner support scanning NFC tags containing the onboarding payload?
- `MCORE.DD.QR_COMMISSIONING` — Does the commissioner support accepting a QR code for commissioning?
- `MCORE.DD.SCAN_QR_CODE` — Does the commissioner support scanning QR codes containing the onboarding payload?

### MCORE.DEVLIST (4)
- `MCORE.DEVLIST.UseDevices` — Does the DUT support to maintain a list of connected devices
- `MCORE.DEVLIST.UseDeviceName` — Does the DUT support to maintain the names of connected devices
- `MCORE.DEVLIST.UseDeviceState` — Does the DUT support to maintain the state of connected devices
- `MCORE.DEVLIST.UseBatInfo` — Does the DUT support maintaining information on battery level of connected devices

### MCORE.FS (1)
- `MCORE.FS` — Does the DUT implement Fabric Synchronization

### MCORE.IDM (35)
- `MCORE.IDM.C` — Is the device a Client
- `MCORE.IDM.C.InvokeRequest` — Is the device a Client and Supports sending a Invoke Request Message
- `MCORE.IDM.C.ReadRequest` — Is the device a Client and Supports sending a Read Request Message
- `MCORE.IDM.C.WriteRequest` — Is the device a Client and Supports sending a Write Request Message
- `MCORE.IDM.C.SubscribeRequest` — Is the device a Client and Supports sending a Subscribe Request Message
- `MCORE.IDM.C.InvokeRequest.BatchCommands` — Is the device a Client and Supports sending multiple commands batched into a single Invoke Request Message
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_Bool` — Is the device a Client and supports Reading an attribute of DataType Bool
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_String` — Is the device a Client and supports Reading an attribute of DataType String
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_UnsignedInteger` — Is the device a Client and supports Reading an attribute of DataType Unsigned Integer
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_SignedInteger` — Is the device a Client and supports Reading an attribute of DataType Signed Integer
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_Struct` — Is the device a Client and supports Reading an attribute of DataType Struct
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_FloatingPoint` — Is the device a Client and supports Reading an attribute of DataType Floating Point
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_List` — Is the device a Client and supports Reading an attribute of DataType List
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_OctetString` — Is the device a Client and supports Reading an attribute of DataType Octet String
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_Enum` — Is the device a Client and supports Reading an attribute of DataType Enum
- `MCORE.IDM.C.ReadRequest.Attribute.DataType_Bitmap` — Is the device a Client and supports Reading an attribute of DataType Bitmap
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_Bool` — Is the device a Client and supports Writing an attribute of DataType Bool
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_String` — Is the device a Client and supports Writing an attribute of DataType String
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_UnsignedInteger` — Is the device a Client and supports Writing an attribute of DataType Unsigned Integer
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_SignedInteger` — Is the device a Client and supports Writing an attribute of DataType Signed Integer
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_Struct` — Is the device a Client and supports Writing an attribute of DataType Struct
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_FloatingPoint` — Is the device a Client and supports Writing an attribute of DataType Floating Point
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_List` — Is the device a Client and supports Writing an attribute of DataType List
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_OctetString` — Is the device a Client and supports Writing an attribute of DataType Octet String
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_Enum` — Is the device a Client and supports Writing an attribute of DataType Enum
- `MCORE.IDM.C.WriteRequest.Attribute.DataType_Bitmap` — Is the device a Client and supports Writing an attribute of DataType Bitmap
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_Bool` — Is the device a Client and supports subscribing to an attribute of DataType Bool
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_String` — Is the device a Client and supports subscribing to an attribute of DataType String
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_UnsignedInteger` — Is the device a Client and supports subscribing to an attribute of DataType UnsignedInteger
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_Integer` — Is the device a Client and supports subscribing to an attribute of DataType Integer
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_FloatingPoint` — Is the device a Client and supports subscribing to an attribute of DataType FloatingPoint
- `MCORE.IDM.C.SubscribeRequest.Attribute.DataType_List` — Is the device a Client and supports subscribing to an attribute of DataType List
- `MCORE.IDM.C.SubscribeEvent` — Is the device a Client and supports subscribing to an individual Event
- `MCORE.IDM.C.ReadEvent` — Is the device a Client and supports Reading an individual Event
- `MCORE.IDM.C.SubscribeRequest.MultipleAttributes` — Is the device a client and supports subscribing to Multiple Attributes

## Type 5 — Manual (product-specific; promote to input or review per device)

Not covered by any input or rule today. Default-ON under 'maximum options', but genuinely vary per product. Grouped by namespace.

### MCORE.BDX (10)
- `MCORE.BDX.Sender` — Does the DUT support the BDX Sender role?
- `MCORE.BDX.Receiver` — Does the DUT support the BDX Receiver role?
- `MCORE.BDX.SynchronousSender` — Does the DUT support the BDX Sender role in Synchronous mode?
- `MCORE.BDX.SynchronousReceiver` — Does the DUT support the BDX Receiver role in Synchronous mode?
- `MCORE.BDX.AsynchronousSender` — Does the DUT support the BDX Sender role in Asynchronous mode?
- `MCORE.BDX.AsynchronousReceiver` — Does the DUT support the BDX Receiver role in Asynchronous mode?
- `MCORE.BDX.Driver` — Does the DUT control the rate of the BDX transfer ?
- `MCORE.BDX.Initiator` — Is the DUT an Initiator of the BDX transfer?
- `MCORE.BDX.Responder` — Is the DUT a Responder of the BDX transfer?
- `MCORE.BDX.BlockQueryWithSkip` — Does the DUT support sending the BlockQueryWithSkip message?

### MCORE.DD (11)
- `MCORE.DD.CHIP_DEV` — Does the commissionee device only function within a Matter network?
- `MCORE.DD.NTL` — Does the DUT support NFC Transport Layer for commissioning?
- `MCORE.DD.UI` — Does the DUT support user interface?
- `MCORE.DD.CONCATENATED_QR_CODE` — Does the commissionee device’s Onboarding Payload contain concatenated QR codes?
- `MCORE.DD.DISCOVERY_PAF` — Does the commissioner or device support Discovery Capability over Wi-Fi PAF?
- `MCORE.DD.NON_CONCURRENT_CONNECTION` — Does the commissionee require Non-concurrent connection commissioning flow?
- `MCORE.DD.USER_INTENT_COMM_FLOW` — Does the DUT support User-Intent Commissioning Flow?
- `MCORE.DD.CUSTOM_COMM_FLOW` — Does the DUT support Custom Commissioning Flow?
- `MCORE.DD.PHYSICAL_TAMPERING` — Is commissionee device subject to physical tampering (doorbell, camera, door lock, designed for outdoor usage)?
- `MCORE.DD.EXTENDED_DISCOVERY` — Does the commissionee device support Extended Discovery through DNS-SD advertisements when device is not in commissioning mode?
- `MCORE.DD.ESF_TC_COMMISSIONER` — Does the commissionee support Enhanced Setup Flow Terms and Conditions?

### MCORE.DLOG (2)
- `MCORE.DLOG.S.UTCTIMESTAMP` — Does the device support UTCTimeStamp field in the RetrieveLogsResponse Command of the Diagnostic Logs Cluster?
- `MCORE.DLOG.S.TIMESINCEBOOT` — Does the device support TimeSinceBoot field in the RetrieveLogsResponse Command of the Diagnostic Logs Cluster?

### MCORE.DT_SW_COMP (1)
- `MCORE.DT_SW_COMP` — Is DUT Software Component?

### MCORE.G (1)
- `MCORE.G.MULTIENDPOINT` — DUT(Server) support multiple endpoints with a Groups cluster

### MCORE.IDM (2)
- `MCORE.IDM.S.LargeData` — Is the device a Server and capable of generating large data which is greater than 1 MTU(1280 bytes)
- `MCORE.IDM.S.PersistentSubscription` — Is the device a Server and supports Persistent subscription

### MCORE.OTA (4)
- `MCORE.OTA.HTTPS` — Does the DUT support the HTTPS Protocol for OTA image download?
- `MCORE.OTA.RequestorConsent` — Does the DUT support obtaining user consent for OTA application by virtue of built-in user interface capabilities?
- `MCORE.OTA.Resume` — Does the DUT support resumption of a transfer previously aborted?
- `MCORE.OTA.Retry` — Does the Requestor DUT support querying a different Provider in its OTA Provider List when it hits error conditions in invoking the QueryImage command?

### MCORE.SC (2)
- `MCORE.SC.EXTENDED_DISCOVERY` — Does device support Extended Discovery for Commissionable Node Discovery?
- `MCORE.SC.TCP` — Does Device support TCP?

