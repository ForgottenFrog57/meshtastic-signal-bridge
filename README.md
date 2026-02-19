# The Minneapolis Fork
##meshtastic-signal-bridge


---

## Introduction

This project is born of a practical response to the limitations of the Signal protocol used by the Twin Cities metro community in early 2026.  Signal is an *excellent* prtocol for community response, and indeed, most of our successes may have been impossible without it.  It does, however, have certain limitations - a 1000 user room limit, a dependence on traditional internet infrastructure, and a tendency for the client to lock up or crash when under *extreme* loads.

Hence, the need for a backup protocol for basic notifications and alerts.  The Twin Cities has a robust Meshtastic network already in place.  And while Meshtastic has its own limitations (for one, an inability to whitelist channel memberships), we feel it can be an effective complement and fall-back to Singal in situations of impromptu community response.

This bridge is an attempt to help faclitate that backup, and help folks to overcome the onerous network effects that would otherwise make it difficult to get folks onto another protocol.  Things seem to have slowed down here a bit for a moment, but if you all find yourselves in a similar situation, we hope you'll find this to be useful : )

## The Fork
The original version of this repository focused primarily on mesh-to-signal traffic.  This version, while keeping most of the original capabilities as alternative options, is focuesd instead on facilitating signal-to-mesh communications as a fall back notification system.  It anticipates a certain level of counter-behavior from "bad faith actors" seeking to take advantage of meshtastic's permissive stance on sending messages to channels.  You'd still have to manually block idiots with the mesh channel key, but with options to restrict traffic from mesh-to-signal and even drop it entirely, we aim to keep the effects of bad behavior to the level of a rather impotent nuisance rather than letting it escalate into a crippling crisis.

The original creator included several features that were notably counter-productive in that context.  The default run mode is now "mode2" (signal-to-mesh only).  This is the only run mode we currently recommend for community response.  The commands to allow mesh users to disable the bridge or switch modes are inaccessible from mode2.  We've included an environment option for disabling reads of the meshtastic queue entirely, tho we suspect there's still some room for improvement on preventing abusive mesh users from triggering wasteful message processing.

We've also included the option to let users opt-in to message forwarding by adding emojis to their username.  This may seem like an odd choice, but "emoji flagging" proved to be a very effective improptu method of assigning roles in the context of signal-based community response, and this filter mode is intended to leverage this natural community practice.  See the '.env.example' file for some more details.

---

## How it works

A dedicated Meshtastic node is connected via USB to a host running the container.  
That node acts as a gateway between:

```
Meshtastic channel  ⇄  Bridge node  ⇄  Signal group
```

**Multiple mesh users** in a private mesh channel can communicate with **multiple Signal users** in a private Signal group. Messages are automatically relayed back and forth between platforms.

Messages on each side are represented as a **single virtual user** and are prefixed with the original sender identity, per platform:

```
[A123] Hello from mesh
[Joe] Hello from Signal
```

[See example convos below](https://github.com/ccwod/meshtastic-signal-bridge?tab=readme-ov-file#-relayed-messages-appear-to-come-through-as-single-users)

---

## Important Requirements

This project assumes that:

- You have a basic understanding of Meshtastic, node configuration, and node placement 
- You already have access to a **city-wide or well-covered Meshtastic mesh** (check out [local Meshtastic groups](https://meshtastic.org/docs/community/local-groups))
- You have Docker Compose (recommended) or Docker running on a Linux host, such as:
  - NAS (e.g. Unraid)
  - Home server
  - Raspberry Pi
  - Always-on Linux computer
- You own a Meshtastic node (e.g. **SenseCap T1000-E**, Heltec V3, T-Beam, RAK WisBlock) that is connected via USB to the host - must be capable of serial connection
- The bridge node is well connected to the wider mesh (Likely requires an accompanying home base node for solid rx/tx. Ask your local mesh community.)

---

## Getting Started

#### Prior to building the container for the first time, complete the following:
1. Configure a secondary Meshtastic channel on the bridge node that will be shared with other nodes (same channel, name, and key). Mesh devices that will interact with the bridge must be configured to the same secondary channel slot.
2. Plug your Meshtastic node into the host using USB and ensure it's powered on.
3. **(Recommended)** Create a udev rule on the host OS so the device always appears at a stable path (e.g. `/dev/meshtastic`) regardless of which USB port is used or how the kernel enumerates it. Without this, the path can change between `/dev/ttyACM0`, `/dev/ttyUSB0`, etc. across reboots or replugs.

   ```bash
   # Find your device's vendor and product IDs
   udevadm info -a /dev/ttyACM0 | grep -E "idVendor|idProduct"

   # Create a udev rule (replace XXXX and YYYY with your IDs)
   echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="XXXX", ATTRS{idProduct}=="YYYY", SYMLINK+="meshtastic"' \
     | sudo tee /etc/udev/rules.d/99-meshtastic.rules

   # Reload and trigger
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

   Then set `MESH_DEVICE=/dev/meshtastic` in your `.env`. See `.env.example` for more details, including per-serial-number matching for multi-device setups.

4. Create a Signal group in the app. This is the group that will be used to interface with the bridge.

---

## Installation

### Docker
1. Create a project directory: `/meshtastic-signal-bridge`
2. Create an `.env` file in the root directory with the following contents; see .env.example for additional info:
```
# Required for Signal - GroupIDs listed on startup after Signal auth
## You can also provide a string to match with a signal group name.  We recommend switching to SIGNAL_GROUP_ID after testing is complete, as signal group names are subject to change.
##SIGNAL_GROUP_ID takes precedence over SIGNAL_GROUP_NAME if both are defined.
SIGNAL_GROUP_ID=
#SIGNAL_GROUP_NAME=

# Required for Meshtastic - MESH_DEVICE USB path listed on startup
MESH_DEVICE=
MESH_CHANNEL_INDEX=1

# Optional tuning
SIGNAL_SHORT_NAMES=TRUE
SIGNAL_POLL_INTERVAL=2
NODE_DB_WARMUP=10
TZ=America/Chicago
LOG_LEVEL=INFO

#Username Filters - see .env.example for more info
#SINGAL_FILTER_ENABLED=true
#SIGNAL_FILTER_CHARS=
```
3. Create a `.docker-compose.yml` file in the root directory with the following contents:

```
services:
  meshtastic-signal-bridge:
    image: ghcr.io/ccwod/meshtastic-signal-bridge:latest
    container_name: meshtastic-signal-bridge
    restart: unless-stopped
    privileged: true
    env_file:
      - .env
    environment:
      - MESH_DEVICE
      - MESH_CHANNEL_INDEX
      - SIGNAL_GROUP_ID
      - SIGNAL_POLL_INTERVAL
      - LOG_LEVEL
      - SIGNAL_SHORT_NAMES
      - TZ
      - NODE_DB_WARMUP
      - MESH_TO_SIGNAL
      - RELAY_MODE
      - DEV_MODE
      - SIGNAL_FILTER_ENABLED
      - SIGNAL_FITLER_CHARS
    volumes:
      - ./signal-data:/root/.local/share/signal-cli
      - /dev:/dev
    restart: unless-stopped
```
4. Build and deploy your container with 'sudo docker compose up -d --build'
5. Open the logs to start the onboarding process with 'sudo docker logs -f mesh-signal-bridge', explained below under [Post-installation](https://github.com/ccwod/meshtastic-signal-bridge?tab=readme-ov-file#post-installation).

---

## Post-installation

#### On first startup the container will:

1. Prompt you to link your Signal account using a QR code.
2. Help you find your Signal group ID.

The logs will guide you through the initial setup.

#### After the first run:
1. Enter the environment variables for **SIGNAL_GROUP_ID** and **MESH_DEVICE** in .env variable section.
2. Rebuild the container/compose down and up to restart the container with your new variables applied.
3. If the container is configured correctly, you will see a startup sequence begin in the logs. Once the sequence reads "Bridge active - relaying messages", then the bridge is fully operational.

---

## Environment Variables
#!update
See `.env.example`

| Variable | Purpose | Default
|---|---|---|
| `SIGNAL_GROUP_ID` | ID of the target Signal group to communicate with, provided during startup after Signal account auth | `NONE` |
| `SIGNAl_GROUP_NAME` | String for matching the name of the Signal group; if used the container will post the matching name and group id it found to the logs; SIGNAL_GROUP_ID takes precedence, and is recomended for prod operation
| `MESH_DEVICE` | USB path of the connected Meshtastic device. Listed on startup, typically something like `/dev/ttyACM*` or `/dev/ttyUSB*`; if you set a udev rule for your host it should be `/dev/meshtastic` | `NONE` |
| `MESH_CHANNEL_INDEX` | Channel index # for Meshtastic device to communicate on (0=PRIMARY), (1=SECOND), (2=THIRD), etc... 0 not allowed | `1` |
| `SIGNAL_SHORT_NAMES` | Signal display name based on Signal profile name. `TRUE`=first string of name, like `[Joe]`. `FALSE`=full Signal profile name, like `[Joe J Lastname]`.  | `TRUE` |
| `SIGNAL_POLL_INTERVAL` | How often signal-cli is polled for new received Signal messages, seconds. Recommend do not change. | `2` |
| `NODE_DB_WARMUP` | How many seconds to wait on for Meshtastic node list to populate on bridge startup, seconds. Recommend do not change. | `10` |
| `TZ` | Timezone used for logging. Common US options: `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`.  | `America/Chicago` |
| `LOG_LEVEL` | Log level | `INFO` |
| `MESH_TO_SIGNAL` | Blocks traffic from mesh entirely when set to `off`, including all commands; this is reccomended if youre running a forward to a general notification channel: `on`, `off`, `echo` | `on` |
| `SIGNAL_FILTER_ENABLED` | If `true`, the bridge will only forward messages from users w the filter characters included in their username; emojis are the reccomended flag here | `false` |
| `SIGNAL_FILTER_CHARS` | List of characters to search usernames for; unicode is accepted, and emojis are the recommended flags here | `NONE` |
| `DEV_MODE` | Requires a '🔧' in signal usernames to forward messages, also tied to some other behavioral changes
| `RELAY_MODE` | Sets operation mode; mode 2, signal-to-mesh only, is currently the only recommended mode for non hobby/testing uses | `1`, `2`, `3` |
 
---

## Commands

### Mesh Commands
Commands can be initiated by all mesh users using the format **![command]**, or **!help [command]**. The bridge will respond back to the mesh channel for each given command, but nothing command-related will be relayed to Signal.



| Command | Purpose |
|---|---|
| `!test` | Verify the bridge is online by sending the hop distance from user to bridge |
| `!help` | Show command help and command list |
| `!help [command]` | Get help with a specific command |
| `!on` | Enable full message relay functionality, according to mode. Default. |
| `!off` | Disable all message relay functionality |
| `!mode` | Shows the mode options, `!Mode[1,2,3]` |
| `!mode1` | Automatically relay all messages between Mesh and Signal. Default. |
| `!mode2` | Relay all Signal → Mesh. Mesh → Signal relay **REQUIRES** `!relay [message]` |
| `!mode3` | Mesh → Signal **ONLY** via `!relay [message]`. Signal → Mesh relay **DISABLED**. |
| `!status` | Show relay state (`on` or `off`) and mode |
| `!relay` | Only used for Modes[2,3]. Explicitly relays messages from Mesh to Signal, otherwise they are not automatically relayed in those modes. |

**NOTE** for security purposes, `!mode1`, `!mode2`, `!mode3`, `!on` and `!off` are all disabled in mode 2.  If MESH_TO_SIGNAL=off, all mesh commands will all fail silently.

### Signal Command

Signal users have access to the **!status** command to check the current configuration of meshtastic-signal-bridge, set by mesh users. This also allows Signal users to ensure the bridge is operational. 

| Command | Purpose |
|---|---|
| `!status` | Show relay state (on or off) and mode |

---


### 🔴 Security and Trust

It should go without saying, but anyone added to a signal group or with the key to a meshtastic channel can read all of the messages inside of them.  And since theres really no keeping other folks from getting a hold of that meshtastic key and watching the content anonymously, we recommend that the bridge only be employed for **community notitications**.  Only deploy this bot to signal chats that folks would be comfortable broadcasting, leave it out of more private groups.

---

### 🔴 Only tested on a limited hardware configuration

- Built and tested using Docker
- Tested with **SenseCap T1000-E**

---

### 🔴 Supported content types

meshtastic-signal-bridge only supports relaying basic message body content due to the fact that Meshtastic is an extremely low-bandwidth platform.

#### From Meshtastic

| Feature | Supported |
|---|---|
| Text messages | ✅ |
| Emoji reactions from Mesh | ✅ (as text) |
| Other device telemetry | ❌ |

- Messages are kept intentionally short for reliable mesh delivery.

#### From Signal

| Feature | Supported |
|---|---|
| Text messages | ✅ |
| Message reactions | ❌ |
| Replies / quotes | ❌ |
| Images / media | ❌ |
| Chat events | ❌ |

 - While replies/quotes are not supported, the main message body content will be relayed; it just won't contain the contextual replied-message content.

---

### 🔴 Link the bridge with a secondary Signal account if possible

If you use **your own Signal account** to link to the bridge, Signal **will NOT notify your phone of new messages** coming from the mesh. The scenario for this would be if you are planning to actively communicate with the Signal group on your phone, and you used the same Signal account to link to the bridge. In that case, when mesh users send messages (which are then relayed by the bridge into the Signal group), you will not receive a mobile notification from the Signal app about new messages from mesh users.

This is because Signal does not notify you for messages sent **to/from yourself**, which is technically what's happening when they come in through the bridge using signal-cli.

**Recommended setup:**
- Use or create a **secondary Signal account** (second phone / number, or use a trusted friend or partner's Signal account)
-- jmp is an excellent, if clunky, choice for getting cheap, effective and anonymous phone numbers
- Add the secondary account to the Signal group
- Link the secondary account to the bridge
- Keep your primary account in the group for personal mobile usage
- This way **will** alert your phone on your primary account when new messages come in from the mesh

---

### 🔴 Relayed messages appear to come through as single users

Messages on each side are represented as a **single virtual user** per platform. Messages are prefixed with a basic sender identity from the other platform.

#### Meshtastic

A USB connected bridge node is required to facilitate mesh interactions. Any messages received from Signal on the mesh side will appear to originate from the bridge node. Messages relayed from Signal will be prefixed with the `[SIGNAL NAME]` of the sending Signal user, but will appear as being sent from the bridge node. Messages between mesh users in the mesh channel group will appear normally. This is how a 2-way conversation could look from the mesh side:
```
NOD1: Hey guys

NOD2: Signal, can you hear us?

BRDG: [Joe] Coming in good

BRDG: [Tom] Yep

NOD1: Great, thanks

BRDG: [Tom] See you soon
```

#### Signal

Similarly, the bridge must be linked to a single Signal account to properly connect to the Signal group. Messages received in the Signal chat from mesh users will appear to originate from a single Signal user, prefixed with the `[NODE]` short name of the sending node. Messages between Signal users in the Signal group chat will appear normally. Conversely, this is how the same 2-way conversation would look from the Signal side:
```
Joe: [NOD1] Hey guys

Joe: [NOD2] Signal, can you hear us?

Joe: Coming in good

Tom: Yep

Joe: [NOD1] Great, thanks

Tom: See you soon
```

---

### 🔴 Do NOT use Channel Index 0 (Primary) for MESH_CHANNEL_INDEX

Channel 0 is the primary, public channel on Meshtastic by default, and thus, we don't want to spam the precious mesh network. It is possible to set Channel Index to 0 for limited testing, however, the bridge is constrained in this mode.

When `MESH_CHANNEL_INDEX=0`:

- **Mesh → Signal works**. You can test and ensure messages are being relayed to the Signal group. Suitable when you're testing the bridge but don't have an extra node or node-friend to send messages to the bridge; you can just listen to the public mesh chatter and check that it's going into Signal.
- **Signal → Mesh is blocked**, intentionally. We don't want to spam a mesh's open, public channel with the vast and numerous contents of a Signal group.
- Logs will explicitly warn you when Channel Index is set to 0.

**Recommended Setup:**

Create a **secondary channel** on all nodes:

- Same channel number
- Same channel name
- Same key (if using encryption, recommended)

[Meshtastic Docs - Channel Config Values](https://meshtastic.org/docs/configuration/radio/channels/#channel-config-values)

----

## ⚠️ AI Code Policy ⚠️

The original repo this is based on was self-proclaimed as "vibe coded".  At least one human has made multiple line-by-line reviews of the code state since then.

The world is changing, like weirdly fast.  Its now possible to generate code with less effort than it takes a human being to read and understand it.  This can lead to a new imbalance between contributors, reviewers and users; in other words, we understand that its possible to effectively waste another human beings time and attention by generating code without demonstrating an ownership and effort equal to that asked by the act of making a pull request.

For the time being, we can only state that we have done the work to review what we're offering and that we are confident that we are respecting your time when we ask you to consider using it.  We ask the same from any other contributors who use choose to use AI to help them create potential improvements.

 ..............................................................:::::::.:::..::::::::....:....:::::::::::.............................. ... .......:::::..................... 
 ........................................... ........................................................................................................ ...................... 
 .................................................:-==-:................................................. .........................................:::::.................... 
 .................................................-*%%+=::.......................................................................................:::........................ 
 ..............................................=@@@@@#%*==:...............................................................................::--:::::......................... 
 ...........................................*@@@@@@@@@#*---:........................................................................................:....................... 
 ........................................+@@@@@:@@@@@@+=--:.:..............................................................................:::....::::.....................: 
 ......................................:%@@@.@@@@@@@@@*::=-:.::...................:::............................................................::...............:::::::::. 
 .....................................+@@@=@@@@*....:-=-::--:.::.........................................................................................::::::::::::::::... 
 ....................................*@@+@@@#........::-:.:--:.::............................................................... .......................::::::.............. 
 ...................................+@@.@@@=.........:::::.:-:..............................................::::::....................................::.................... 
 ...................................@@=@@*.............:::..::.......................................:::::..::::::::::::::::.....::::.............::::.................:.... 
 ..................................+@@@@@...............:....::.......................................:::.........:::::::::::::::::..:::.....::.................:::......... 
 ..................................@@=@@-.............:......:::::::::::::...........:..:::::::::::.....::::...................::........................................... 
 ...................::::...........@@@@@.............::......::::::::::::::::::::::::::::::::::::::::::::::::::............................................................. 
 .................:::::::::::......@@@@=..:::::::::::::::::::.::::::----------------=====------------:::::::::...::......................................................... 
 ...............:::::::::::::::::::@@@@:::::::::::::::::::::..:--::----==++*****++*##%@@@@@%#*+++++==---::::::----:::::::::................:::::::............:::::::::::::: 
 .......::::....:::::::::::::.::::.@@@@*-:-------::::::::::.::-==::::::----====++*#@@@@%@@@@@%#*###*+=-:::::---:::::::::::.............:::::::::::::::::........:::---:::::- 
 ...........:........:::::::::+@@@@@@:@@@@%=.:-======----:+@@@@@@@@@@*.:--=+*#%@@@%*+=@@@@@@@:-::::::-:::::::::....:...........::::::::.........:.............:::::::::::::: 
 ......::::.:....::::::..::.+@@@@@@@@+*@@@@@#*=:-====----:@@@@@@@@@@@@@@@@@@@@@@@@@@+@@@@@@@@@@%=---:.::..........:::::::::::::::--::::::...............::::------::........ 
 ......::::.....:::::::::::@@@@#+==--::--=@@@@=:------:*@@@@:.....::@@@@@@@@@@@@@@@@-@@@@@@@@@@@::::...:...................................................:................ 
 ::::........::::::::::::.@@@*-:..::::::::-#@@@@@@:.=@@@@@@@:.....::=%*..........-@@=@@%:-=-@@@@*-:::..........................................:::::-=-:::......::::........ 
 .....::::::---=======--*@@@+::........:::.-#@@@@@#:@@@@@@@%-=:-=::.:--=:........:@@@@@--==*@@@@@:::#%+:::::...:+@@+........:................::::::::::::................... 
 .::::::....:::::::::*@@@@@@-:.........::::-+#@%@@@:@@@*.+*:+.**+=:-%@+-=::::-:---@@@@#:--::+@+@@@@@@@@@@@++++=-@@@@*@@@@@@@@%=@@@+----====---::----::::-::::...........:-:. 
 -:.=#%@@@@@@%-.::--*@@@@@#=:............:::--=*%@@=@@@-:-%=*:+%-*==+-##++++=-.-==@@@@-:-:++-%-*@@@@@@@@@@@@@@@@@@*@%@@@@@@@@@@@@@@@@=:::::::.+@@@*+**##%%%#*+--::**+##+@@@@ 
 @@@@@@@@@@@@@#::-#@@@@-:=-...................:=@@@@@@@.::@++=-*-#=*@@#*.#*=#-.-=*@-@=.-::*--%=.+:.#::=@:*@@@@@@+@=@#@--+**=+@@@#@@@@@.*@@@*=@@@@@@#@@@@%=#@@==*#@@@@%:@@@@@ 
 @@%*+#%*..-@@@@@@@@@@==@%#-..................:-@@@@@@...=*+-::=-*-*=--*-+#-+=-+#-@*@-:--=.=:+:=-::*:.:@-+#%#@@@@@-@*@--:.::-*@+-+%@@@+@@@@@@@@@*@@@@@@@@@@@@@@+%@@@@@@@@+-+ 
 ##+#%%+-..-=@@@@@@@@@+@#-+=:...............*%+*@@@@@+.=#==-=---*=--:--#=-+=.+#@@@@%@.:::-==****:::-=+=*-##*=**@@#.@*@-=:.-=+%%..:+#@@@@@#@@@@%.:+@@@@#@@@@@@@@@@@@+*@@@@... 
 =*+++=..--=-.+*+*+++:@@++=-:...............%:*#+@@@@--+-=-:==.-==++*%-@==+:+*+#@@@@@:..:+::+#+-=--++=++%@%+-:=@@#*@@@=+=:=#*#+...-*@@@@#.=++::..:*+#=.-#**:=#@@@%-=--+=:.:= 
 :-::-:..=:.---::-::-:@+%===++=:..::::::::=#%-#=+=:---::*-+*:=-=---%+#*#+-#=.+:.@@@@@:.::-=--#%#--+::-#+=-=:+*==%@#@@@.:-+=@::-.:--+@@@@-===+=--==-.--:-=:=-+-*#%::-:.:----- 
 -:-:=:::-::-=-:.-=-.:@+#**#%%#*=@@@@@@@@@@@@@@@@%+-:--::++:::+-=-+*+-=:#+-**%+=%@@@=...--:.:=+*=#@@@@%=:.=:-:::=+#*#==+*@%@:::.:::-*@@-....::.......:.::--.-++==::.......:= 
 -----.:.:::--.:::...-@%*@@%##%%%@@@@@@@@@@+:::=@@@@+--::-#*=+-=+=--+*:++%==+*-+++@%:::-:::::=+%@@#*#@%*+*=-+*+=-+#%#+##*%@*--:.:-===+===++++=--=====---=====--==:-=--==---: 
 =+*+=------:::::-=--=@@+#@%**#@@@@%%#%@@@*---:::+@@@+:--:--*#==::+-:+====-+%@**==%*-::-=---.=##*-:::.....::..............:....:...:::...................................... 
 .....................#@@*+%###@@@@%@#=+@@@#=--::::*@@@*..::=%#*=+**+-+=+.#=*#+*--*---.....=.=#*-........................................ ........... ..... ................ 
 .....................:@@@%+@@@@@#*#@@@@*#@@+=---:::*@@@*.:::+*=+*###=%@@@@@@@@@@@@@@@#:..::-=:=-.:......................  ............................ ................. .. 
 ......................=@@@@@@@@#-==+*%@@%%@@*=---::::*@@#.--:-:.#@@%@@*+:=%@#%@@@@@@@@@@@@@@@=+:....................................................... ................... 
 ................. .....=@@@@%@= ......-%@@@@@@%*=---::*@@*.-=#@@%*=--@@@@@@@@@@@@@@@%@@@@@@@@@@@@@@@*........... ....... ...................... ............. ............. 
 ::......:::::::...::::::=@@@@@@        :+%%@@@@@@#++==-%@@%@@%+#=@@@*++**:-*#%#+-+@@@@@@@@@@+@@@@@@@@@@@@@@%-===--:......::::........::::.........::......................: 
 ::::::::::::::::::::::::::*@@@@@@      .:=*###%@@@@%%#*+@@@%=*@@-@@@@@@@@@%+=:=+::=*%@@@@@@@@@@@@@@%@@@@@@@@@@@@@@@--------------:::::::-:::...::::----::.::::::::::::.:::: 
 ##%@@%%####%%#%@@@%%@@@@@@@@=@@@@@@     ..:=+**##%%%%%##@@@@@#-@@@@%*+%%+=%*#%%=:-=@@#*=-.+*#@@@@@@@@@@@@@%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@ 
 #%%@%######%@@@@@@@@@%@@@@@+--+@@@@@@      .:=++**++****@@@%::%@+#@**==+=-==++--+=-=@@@@@@@*====++#%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@%@@%%%%%@@@%@@ 
 ::-..---------::.:-:.:-=+*#%#*#%%@@@@@@@    ..:-=+****%@@@+:..#@@@@@%-.-=--:-:-.-=--=+-:::=+*=:-*##=::.=*%@@@@@@@@@@@@@=@@@@@@@@@@@@@@:::-+++--::++=:.:--:::------:..-=+=@: 
 :-.-:+##+#*::--:..:--=#@@@@%**+==+#@@@@@@@@@  ...:-++@@@@::.:-++:-.=@@@@@@@@@@@@@@@@@%*@@@@@@@@@@@@%+::-+.%@#%@@@@@@@@@@@@@@@%+@@@@@@@@@@@@@+---::.:===----::-===--------@% 
 +*+*#@*+-=+++-+--=+=:=%##@@@@@@%@@@@+=@@@@@@@@@@@-.*@@@@:::-:-=++**#@-==++.:-*#####%@@@@@@@@@@@@@@@@@@@@@+@*=+##@@@@@@@@@@@@@@@@@@@@+@@@@@@@@@@@@-.-++***-:++++===++++=--*+ 
 +*#*+@@@@@@++*=:.-.--=-=++***%@*==+=+++-==*@@@@@@@@@@@@.+@@@@@@@@@@@@@@@@@@@@@@@@@@@%=-=..:::......++**+%@@*@%*****%@@@@@@@@@@@@@@@@@@@@@@@:@@@@@@%%@@@@@%#*+**#%**+*%%+=*# 
 ===-.:=+%@%#***##*+##@@@@@@%***===**-:-:...=*+=#@@@@@%@@@@%*####%@@@#*+**##**+=**-==---:...::......:=-:::+=::..--.:::-++***#%@@@@@@@@@@@@@@@@@@@#@@+===-+*-.:::=--:::=-=.:- 
 :-:::--==+*##***%%*%@#=-*+-.--=:----+=-:...:+###*=+*%@*=:%@@@@@@@@@@@@@@@@@@@@@@@*#**+-:....-:-=#@#--:::::::...:.:..:::--:--===+#@@@@@@@@@@@@@@@@@@:::::-*.:--=*===-.:.==%@ 
 :::....:::....:--::::...:-----.::..:-+==**#@@@@@@@@#-+@@@@@%#**##@@@@@@@@@@@@@%#+:+=::::::..--:-*=@@@@+:-.:-=.:--==+*=:-=**=:..==-+#++==#%#*++*#@@*::..::+---::=----:::+++- 
 -=====---===+++==-=====-:::--==:::=+*%@##@@%%%**#**+***=-::--====--=-=:------==-+.*=-:....::::-@@--*@@@@@*==++--.:..:-=*#*++=--:-==+=+--++===-::::--===-.-*+=-=----===+##%@ 
 -:::--::-=----:::--:::::::::=*===*@@@@@%*+=:-+###%%#*+**=--:.:.:::-=:..-::::.:::*=%@@@@@@@@@@@@@@@-*-*@@@@@@@@@@@@@@@@@@@@#+:.:.-::.-=---:.....:.::....--======-::---::=*-% 
 :-::.:::-.::::.:...:-.--::-:-+=-%@@##*==*=-::=-=+=-=====-:::--::...-:...:-+**+#@@@@@@@@@@@@@@@@===#-*+:=+@@%%%@@@@%@@@@@@@@@@%#**@@@@@#+%@@%@@@@@%##@@@@@@@**%@%%%%%###*=#+ 
 --:.:--:..::-:..:::--=-:::--.#@@@%--+=--:=---=:....-=---:::........-=--+=:+**@@@@#=++.---*:-+:*=**=+-*+##+=:-*+:--=+=:=:=+==++#@@@@@@@@@@@@%@@@@#++##@@*+@@%%@@@*=%%*+=-:=% 
 -::.:--:...---::::-:-=::::==-@@%#*#+#==+.*++==::==++-.--..--:..:=+*@@@@@%#%+=%*=+=:==**+*=-**.-=::.-+=.=--::=-..-:=.+-*=-=--.+*+*====-:==:=--+===--::@@@@@@:--:-*:+--:--:.: 
 -:.::.--...:-:.:::::==:..:++%@%.=-+##-.:*@%#%%*++--::.--=**#@@@@@@@@@*==##+#@=+==*=*+-.-+**+::.:---=-:::=-:.=:--.::-:----*==+=.=%#++=-+##+:=.=:--==::**#=+#*=-.:*--:::=.--- 
 -..::::=-:.:-:.:..-.==-:.-+%@@:+=----+@@@@=:..:-:.:-==+#@@@@@@@@@@#--:=--::%=*:+=::---.-:=*%*::.=-:=-*#*++**=:=-+=.=-:.++%@@#*=+-.-**+=--+-+.=.-.+*=.=*-=:::.-::+:::--++=:: 
 .......::::--:::::-:=-::-==@@%@%+--=+#%***=-::-::=-:=%@@@%#-%-=#%#+++==-+.:#**::.==--:-:::::*+--==-#*%.=+++--:-#*%.=::-==#-=-*%%@+:#:-=*--+=+==-:=+=:=**+=##*+::---=-.:-::+ 
 .::-:....::--.:.:::-=+**++-*@@*%@@@%%#===+*#*-:+%%%@@#++:+#:*+@@%=-=-=+-+.:=+.*#==.=+-=-.=*=+:-:-:--++-.*:+#+=*:*=-=-:-==*=-=*-:-%-+:==+-.:-#++:-+*=::+-:-++.-:::=--::-+*== 
 .......:..:::.::..:::--:.:-++**-:-::-.-*#*#++*+=--:-+**@@=%#:+#=*:-.=:-.+.:-#*#=+:--=:+=.-:-:-:..:==*.==*@@@@::+:=*=+.-+%@@@*-+@@%=+*+%.++*.=**=:--+*

Pictured - Not a Fork, But We're Still Proud of It
