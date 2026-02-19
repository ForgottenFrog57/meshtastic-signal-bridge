import os
import time
import logging
import requests
import serial
import queue
import threading

# -------------------------
# Disable exclusive serial lock
# The meshtastic library opens the serial port with exclusive=True,
# which can cause issues in containerized environments. This
# monkey-patch forces exclusive=False regardless of library version.
# -------------------------
#!we only need this dodgey nonsense if we're running in a docker container
#!even then, its more of a feature for sparing users the annoyance of juggling ports and processes
#on the OS (say, ones that try to access the port when its plugged in)
#!if the meshtastic library changes the name of this function, we have to catch it here too
_original_serial_init = serial.Serial.__init__

def _patched_serial_init(self, *args, **kwargs):
    kwargs["exclusive"] = False
    _original_serial_init(self, *args, **kwargs)

serial.Serial.__init__ = _patched_serial_init

from meshtastic.serial_interface import SerialInterface
from pubsub import pub

# -------------------------
# Safe env helpers
# -------------------------

def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        print(f"{name} invalid. Using default {default}")
        return default


def env_bool(name, default):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")

# -------------------------
# Environment config
# -------------------------

SIGNAL_GROUP_ID = os.environ["SIGNAL_GROUP_ID"]
MESH_DEVICE = os.environ["MESH_DEVICE"]
MESH_CHANNEL_INDEX = int(os.environ["MESH_CHANNEL_INDEX"])
POLL_INTERVAL = int(os.environ["SIGNAL_POLL_INTERVAL"])
NODE_DB_WARMUP = int(os.environ["NODE_DB_WARMUP"])
SIGNAL_SHORT_NAMES = os.environ["SIGNAL_SHORT_NAMES"].lower() == "true"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR"):
    LOG_LEVEL = "INFO"

#!defaults to off if it hasnt been set in env
#!echo is primarily useful for logging confirmation that the bridge has sent its message to mesh and that the mesh is setup
MESH_TO_SIGNAL = os.environ.get("MESH_TO_SIGNAL", "on").lower()
if MESH_TO_SIGNAL not in ("on", "echo", "off"):
    MESH_TO_SIGNAL = "off"

DEV_MODE = env_bool("DEV_MODE", False)

SIGNAL_FILTER_ENABLED = env_bool("SIGNAL_FILTER_ENABLED", True)
SIGNAL_FILTER_CHARS = list(os.environ.get("SIGNAL_FILTER_CHARS", "\U0001f4e2"))

SIGNAL_RPC_URL = "http://localhost:8080/api/v1/rpc"

PRIMARY_BLOCK_MESSAGE = (
    "[BRIDGE] Signal → Mesh relay is disabled while MESH_CHANNEL_INDEX=0 (Primary). "
    "This mode is only for testing Mesh → Signal. Please set MESH_CHANNEL_INDEX to a different channel."
)

COMMAND_PREFIX = "!"
BRIDGE_PREFIX = "BRIDGE"

# -------------------------
# Runtime relay state
# -------------------------

RELAY_ENABLED = True
RELAY_MODE = env_int("RELAY_MODE", 2)

# -------------------------
# Logging
# -------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("bridge")

#!we'll obv have to update this for mode 4
if RELAY_MODE not in (1, 2, 3):
    log.warning("RELAY_MODE=%s is invalid. Defaulting to 2.", RELAY_MODE)
    RELAY_MODE = 2

# -------------------------
# Bridge start time (used to discard old Signal messages)
# -------------------------

BRIDGE_START_TIME = int(time.time() * 1000)

# -------------------------
# Signal to Mesh message queueing
# -------------------------

MESH_TX_QUEUE = queue.Queue()

def mesh_tx_worker(iface):
    while True:
        message, sender_label, log_relay = MESH_TX_QUEUE.get()

        try:
            iface.sendText(message, channelIndex=MESH_CHANNEL_INDEX)

            if log_relay:
                if sender_label:
                    log.info(f"Relayed Signal → Mesh ({sender_label})")
                else:
                    log.info("Relayed Signal → Mesh")

        except Exception as e:
            log.error("Mesh send failed — interface may be down: %s", e)

        time.sleep(3.2)
        MESH_TX_QUEUE.task_done()


# -------------------------
# Formatting helpers
# -------------------------

def format_signal_sender_name(profile_name, phone=None):
    name = profile_name or phone or "Signal"
    if SIGNAL_SHORT_NAMES and name:
        name = name.split(" ", 1)[0]
    return name


def format_signal_to_mesh(sender_name, message_text):
    return f"[{sender_name}] {message_text}"


def format_mesh_to_signal(sender_name, message_text):
    return f"[{sender_name}] {message_text}"


def format_bridge_message(text):
    return f"[{BRIDGE_PREFIX}] {text}"

def build_status_message():
    relay_state = "ON" if RELAY_ENABLED else "OFF"
    return format_bridge_message(
        f"Message relaying is {relay_state}. MODE{RELAY_MODE} is active."
    )

# -------------------------
# Signal RPC helpers
# -------------------------

_rpc_id = 0

def rpc_call(method, params):
    global _rpc_id
    _rpc_id += 1
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": _rpc_id,
    }

    try:
        r = requests.post(SIGNAL_RPC_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Signal RPC error: {e}")
        return {}



def send_to_signal(message, sender_label=None, log_relay=True):
    try:
        rpc_call("send", {
            "groupId": SIGNAL_GROUP_ID,
            "message": message
        })
        if log_relay:
            log.info(f"Relayed Mesh → Signal ({sender_label})")
    except Exception as e:
        log.error("Signal send failed: %s", e)

# -------------------------
# Mesh helpers
# -------------------------
        
def send_to_mesh(iface, message, sender_label=None, log_relay=False):
    MESH_TX_QUEUE.put((message, sender_label, log_relay))

def get_node_display_name(node_id, interface):
    try:
        if node_id and node_id in interface.nodes:
            user = interface.nodes[node_id].get("user", {})
            if user.get("shortName"):
                return user["shortName"].strip()
            if user.get("longName"):
                return user["longName"].split()[0][:8]
    except Exception:
        pass

    if node_id and node_id.startswith("!") and len(node_id) > 5:
        return node_id[1:][-4:].upper()

    return "????"

# -------------------------
# Mesh command handling
# -------------------------

COMMAND_REGISTRY = {}

def mesh_command(name):
    def decorator(func):
        COMMAND_REGISTRY[name] = func
        return func
    return decorator

# ------------------- COMMANDS -------------------

#Test command
@mesh_command("test")
def test(args, iface, ctx):
    hops = ctx.get("hops")

    if hops is None:
        hop_text = "? hops"
    elif hops == 0:
        hop_text = "0 hops"
    elif hops == 1:
        hop_text = "1 hop"
    else:
        hop_text = f"{hops} hops"

    send_to_mesh(
        iface,
        format_bridge_message(f"{hop_text}")
    )

test.description = "!test — Verify bridge is online, hop distance to bridge."

#! these two should be testing only in an adversarial env, 
#the potential for abuse should be obvious
#! as it stands, they are disabled in mode 2 and enabled in modes 1 and 3
#!in a future release they may be enabled in all but a future mode4
#On command
@mesh_command("on")
def relay_on(args, iface, ctx):
    global RELAY_ENABLED

    if RELAY_ENABLED:
        send_to_mesh(
            iface,
            format_bridge_message("Relay already enabled. Use !off to disable.")
        )
        return

    RELAY_ENABLED = True
    log.info(f"Relay ENABLED ({ctx['label']})")
    send_to_mesh(
        iface,
        format_bridge_message("Relay enabled. Use !off to disable.")
    )

relay_on.description = "!on — Enable message relaying."

#!Off command
@mesh_command("off")
def relay_off(args, iface, ctx):
    global RELAY_ENABLED

    if not RELAY_ENABLED:
        send_to_mesh(
            iface,
            format_bridge_message("Relay already disabled. Use !on to enable.")
        )
        return

    RELAY_ENABLED = False
    log.info(f"Relay DISABLED ({ctx['label']})")
    send_to_mesh(
        iface,
        format_bridge_message("Relay disabled. Use !on to enable.")
    )

relay_off.description = "!off — Disable all message relaying."
##############^

#!we cant let unauthenticated user change our mode
#when we expect bad actors
#Mode command
@mesh_command("mode")
def mode(args, iface, ctx):
    send_to_mesh(
        iface,
        format_bridge_message("Use !mode1, !mode2, !mode3, or !help mode1/2/3")
    )

mode.description = "!mode — Set relay modes using !mode[1,2,3]."

#Mode1 command
@mesh_command("mode1")
def mode1(args, iface, ctx):
    global RELAY_MODE
    RELAY_MODE = 1
    log.info(f"MODE1 enabled ({ctx['label']})")
    send_to_mesh(
        iface,
        format_bridge_message("MODE1 enabled. Relay all messages between Mesh and Signal. Default.")
    )

mode1.description = "!mode1 — Relay all messages between Mesh and Signal. Default."

#! we're going to want another one of these but with the !relay command disabled
#Mode2 command
@mesh_command("mode2")
def mode2(args, iface, ctx):
    global RELAY_MODE
    RELAY_MODE = 2
    log.info(f"MODE2 enabled ({ctx['label']})")
    send_to_mesh(
        iface,
        format_bridge_message(
            "MODE2 enabled. Relay all Signal → Mesh. Mesh → Signal REQUIRES !relay [message]."
        )
    )

mode2.description = "!mode2 — Relay all Signal → Mesh. Mesh → Signal REQUIRES !relay [message]."

#Mode3 command
@mesh_command("mode3")
def mode3(args, iface, ctx):
    global RELAY_MODE
    RELAY_MODE = 3
    log.info(f"MODE3 enabled ({ctx['label']})")
    send_to_mesh(
        iface,
        format_bridge_message(
            "MODE3 enabled. Mesh → Signal ONLY via !relay [message]. Signal → Mesh relay DISABLED."
        )
    )

mode3.description = "!mode3 — Mesh → Signal ONLY via !relay [message]. Signal → Mesh relay DISABLED."

#!Status command
@mesh_command("status")
def status(args, iface, ctx):
    send_to_mesh(iface, build_status_message())

status.description = "!status — Show relay state and active mode."

#Relay command
@mesh_command("relay")
def relay(args, iface, ctx):
    if not args:
        send_to_mesh(iface, format_bridge_message("Usage: !relay <message>"))
        return

    message = " ".join(args)
    sender = ctx["label"]

    if RELAY_MODE == 1:
        send_to_mesh(
            iface,
            format_bridge_message("MODE1 enabled. !relay not needed in this mode.")
        )

    if RELAY_MODE in (1, 2, 3):
        send_to_signal(
            format_mesh_to_signal(sender, message),
            sender_label=sender
        )

relay.description = "!relay <message> — Explicitly relay a message using the bridge. Modes[2,3] only."

#!dont want this for adversarial environments, 
#either, leaving this open is just bait; maybe if we had a whitelist of approved nodes?
#Help command
@mesh_command("help")
def help(args, iface, ctx):
    available = get_available_commands()

    if args:
        cmd = args[0].lower()

        if cmd not in COMMAND_REGISTRY:
            send_to_mesh(iface, format_bridge_message("Unknown command. Try !help."))
            log.info(f"Mesh !help for unknown command: !{cmd} ({ctx['label']})")
            return

        if cmd not in available:
            send_to_mesh(iface, format_bridge_message(f"!{cmd} is not available in MODE{RELAY_MODE}."))
            return

        log.info(f"Mesh !help for command: !{cmd} ({ctx['label']})")
        desc = getattr(COMMAND_REGISTRY[cmd], "description", "No help available.")
        send_to_mesh(iface, format_bridge_message(desc))
        return

    cmd_list = ", ".join(f"!{name}" for name in available if name != "help")
    send_to_mesh(
        iface,
        format_bridge_message(f"Try {cmd_list}, or !help [command]")
    )

help.description = "!help [command] — Show help for a command."

# -------------------------
# Mode-based command restrictions
# -------------------------

MODE_BLOCKED_COMMANDS = {
    1: set(),
    2: {"on", "off", "mode", "mode1", "mode2", "mode3"},
    3: {"on", "off", "mode", "mode1", "mode2", "mode3"},
}

def is_command_blocked(command):
    blocked = MODE_BLOCKED_COMMANDS.get(RELAY_MODE, set())
    return command in blocked

def get_available_commands():
    blocked = MODE_BLOCKED_COMMANDS.get(RELAY_MODE, set())
    return {name: handler for name, handler in COMMAND_REGISTRY.items() if name not in blocked}

# -------------------------
# Command dispatcher
# -------------------------

def handle_mesh_command(text, iface, ctx):
    if not text.startswith(COMMAND_PREFIX):
        return False

    parts = text[len(COMMAND_PREFIX):].strip().split()
    if not parts:
        send_to_mesh(iface, format_bridge_message("Empty command. Try !help."))
        return True

    command = parts[0].lower()
    args = parts[1:]

    handler = COMMAND_REGISTRY.get(command)
    if not handler:
        send_to_mesh(iface, format_bridge_message("Unknown command. Try !help."))
        log.info(f"Unknown command: !{command} ({ctx['label']})")
        return True

    if is_command_blocked(command):
        send_to_mesh(iface, format_bridge_message(f"!{command} is not available in MODE{RELAY_MODE}."))
        log.info(f"Blocked command: !{command} in MODE{RELAY_MODE} ({ctx['label']})")
        return True

    log.info(f"Executing mesh command: !{command} ({ctx['label']})")
    handler(args, iface, ctx)
    return True

# -------------------------
# Mesh receive handler
# -------------------------

# Set by main() after connecting to the device
BRIDGE_NODE_ID = None

def on_mesh_message(packet, interface):
    try:
        decoded = packet.get("decoded")
        if not decoded:
            return

        pkt_channel = packet.get("channel")
        if MESH_CHANNEL_INDEX != 0:
            if pkt_channel != MESH_CHANNEL_INDEX:
                return
        else:
            if pkt_channel is not None and pkt_channel != 0:
                return

        text = decoded.get("text")
        if not text:
            return

        node_id = packet.get("fromId")
        if not node_id:
            from_num = packet.get("from")
            if from_num is not None:
                node_id = f"!{from_num:08x}"
            else:
                return

        # MESH_TO_SIGNAL=echo: only log messages sent by the bridge itself
        if MESH_TO_SIGNAL == "echo":
            if node_id == BRIDGE_NODE_ID:
                log.info(f"Echo confirmed: {text}")
            return

        # Skip relayed messages (prefixed with [)
        if text.startswith("["):
            return

        label = get_node_display_name(node_id, interface)
        
        #Get hop count
        hop_start = packet.get("hopStart")
        hop_limit = packet.get("hopLimit")
        
        hops = None
        if hop_start is not None and hop_limit is not None:
            hops = hop_start - hop_limit
        
        ctx = {
            "node_id": node_id,
            "label": label,
            "hops": hops,
        }


        if handle_mesh_command(text, interface, ctx):
            return

        if not RELAY_ENABLED:
            return
        
        # MODE1: allow
        # MODE2/3: block normal messages (must use !relay)
        if RELAY_MODE != 1:
            return

        send_to_signal(
            format_mesh_to_signal(label, text),
            sender_label=label
        )

    except Exception as e:
        log.error("Error handling mesh message: %s", e, exc_info=True)
        log.error("RAW PACKET: %s", packet)

# -------------------------
# Signal polling
# -------------------------

def handle_signal_results(results, iface):
    for item in results:
        env = item.get("envelope", {})

        # -------- DROP OLD SIGNAL MESSAGES --------
        msg_time = env.get("timestamp", 0)
        #if msg_time < BRIDGE_START_TIME:
        #annoyingly, we compare the senders send time to the bridge startup time;
        #in practice this causes dropped messages shortly after startup if the senders 
        #device time doesnt align with our own, this is a dumb fix
        #to a problem that would be agonizing to explain to a large volume of users
        #and yes, i have seen this issue in the wild with "normal" usage
        if msg_time < BRIDGE_START_TIME - (10 * 60 * 1000): #5 minutes
            continue
        # -----------------------------------------

        msg = None
        group = None

        if "dataMessage" in env:
            dm = env["dataMessage"]
            msg = dm.get("message")
            group = dm.get("groupInfo", {}).get("groupId")
        elif "syncMessage" in env and "sentMessage" in env["syncMessage"]:
            sm = env["syncMessage"]["sentMessage"]
            msg = sm.get("message")
            group = sm.get("groupInfo", {}).get("groupId")

        if not msg or group != SIGNAL_GROUP_ID or msg.startswith("["):
            continue

        # -------- SIGNAL COMMANDS --------
        stripped = msg.strip()
        stripped_lower = stripped.lower()

        if stripped_lower == "!status":
            sender = format_signal_sender_name(env.get("sourceName"), env.get("source"))
            status_msg = build_status_message()

            rpc_call("send", {
                "groupId": SIGNAL_GROUP_ID,
                "message": status_msg
            })

            log.info(f"Executing Signal command: !status ({sender})")
            continue
        #!we need some more diagnostic and admin commands on this half of the bridge
        # -----------------------------------------

        if not RELAY_ENABLED:
            continue

        if RELAY_MODE == 3:
            continue

        if MESH_CHANNEL_INDEX == 0:
            send_to_signal(PRIMARY_BLOCK_MESSAGE, log_relay=False)
            continue

        raw_name = env.get("sourceName") or ""
        sender = format_signal_sender_name(raw_name, env.get("source"))
        log.info("Signal message from: '%s' (raw: '%s')", sender, raw_name)
        if DEV_MODE and "\U0001f527" not in raw_name:
            log.info("DEV_MODE: skipping Signal → Mesh for %s (no 🔧)", sender)
            continue

        if SIGNAL_FILTER_ENABLED and not any(ch in raw_name for ch in SIGNAL_FILTER_CHARS):
            log.info("SIGNAL_FILTER: skipping Signal → Mesh for %s (no filter char)", sender)
            continue

        send_to_mesh(
            iface,
            format_signal_to_mesh(sender, msg),
            sender_label=sender,
            log_relay=True
        )

def poll_signal_loop(iface):
    while True:
        try:
            resp = rpc_call("receive", {})
            if resp and resp.get("result"):
                handle_signal_results(resp["result"], iface)
        except Exception as e:
            log.warning(f"Signal poll error: {e}")
        time.sleep(POLL_INTERVAL)

# -------------------------
# Main Startup
# -------------------------

def main():
    log.info("======================================")
    log.info(" Meshtastic ↔ Signal Bridge")
    log.info("======================================")
    log.info("Device: %s", MESH_DEVICE)
    log.info("Mesh channel index: %s", MESH_CHANNEL_INDEX)
    log.info("Signal group: %s", SIGNAL_GROUP_ID)
    log.info("Poll interval: %s sec", POLL_INTERVAL)
    log.info("Node DB warmup: %s sec", NODE_DB_WARMUP)
    log.info("Log level: %s", LOG_LEVEL)
    log.info("Signal short names: %s", SIGNAL_SHORT_NAMES)
    log.info("Relay mode: MODE%s", RELAY_MODE)
    log.info("Dev mode: %s", DEV_MODE)
    log.info("Signal filter: %s (chars: %s)", SIGNAL_FILTER_ENABLED, "".join(SIGNAL_FILTER_CHARS))
    log.info("Mesh → Signal: %s", MESH_TO_SIGNAL)
    log.info("")
    log.info("Connecting to Meshtastic on %s...", MESH_DEVICE)
    
    iface = SerialInterface(devPath=MESH_DEVICE)
    log.info("Meshtastic connected")

    # Store bridge node ID for echo detection
    global BRIDGE_NODE_ID
    try:
        info = iface.myInfo
        my_node_num = info.get("myNodeNum") if isinstance(info, dict) else getattr(info, "my_node_num", None)
    except Exception:
        my_node_num = None
    if my_node_num is not None:
        BRIDGE_NODE_ID = f"!{my_node_num:08x}"
        log.info("Bridge node ID: %s", BRIDGE_NODE_ID)

    log.info("Waiting %s seconds for node database to populate...", NODE_DB_WARMUP)
    time.sleep(NODE_DB_WARMUP)
    
    #Mesh TX queue worker
    threading.Thread(target=mesh_tx_worker, args=(iface,), daemon=True).start()

    node_count = len(iface.nodes) if hasattr(iface, 'nodes') else 0
    log.info(f"Node database ready ({node_count} nodes known)")
    

    log.info("")
    if MESH_CHANNEL_INDEX == 0:
        log.warning("Signal → Mesh relay is DISABLED while MESH_CHANNEL_INDEX=0")

    if MESH_TO_SIGNAL == "on":
        log.info("Mesh commands: !help, !test, !on/!off, !mode[1,2,3], !status, !relay")
    elif MESH_TO_SIGNAL == "echo":
        log.info("Mesh → Signal disabled (echo monitoring active)")
    else:
        log.info("Mesh → Signal disabled (mesh receive off)")

    log.info("Signal commands: !status")
    log.info("")
    log.info("======================================")
    log.info("Bridge active - relaying messages")
    log.info("======================================")

    if MESH_TO_SIGNAL != "off":
        pub.subscribe(on_mesh_message, "meshtastic.receive")

    poll_signal_loop(iface)


if __name__ == "__main__":
    main()
