"""Route confirmed punch feedback to the attacker's connected ESP gateway."""

import protocol as P


HIT_DURATION_MS = 200
PUNCH_NODES = {
    "JAB": 1, "LEFT_HOOK": 1, "LEFT_UPPERCUT": 1,
    "CROSS": 2, "RIGHT_HOOK": 2, "RIGHT_UPPERCUT": 2,
}


class HitFeedback:
    def __init__(self):
        # Only handshaken, currently connected player gateways belong here.
        self.writers = {}

    async def send_hit(self, event):
        if event["outcome"] != "HIT":
            return
        player = event["source_player"]
        node = PUNCH_NODES[event["punch"]]
        await self.send_pulse(player, node, event["attack_id"])

    async def send_pulse(self, player, node, action_id="manual"):
        if player not in (1, 2) or node not in (1, 2):
            raise ValueError("player and hand node must be 1 or 2")
        writer = self.writers.get(player)
        if writer is None or writer.is_closing():
            print(f"[HAPTIC SKIP] id={action_id} P{player}: gateway offline", flush=True)
            return
        # The player's right gateway drives node 2 locally or forwards node 1
        # over ESP-NOW. Never queue or retry a physical effect on reconnect.
        writer.write(P.actuate(node, 1, HIT_DURATION_MS))
        await writer.drain()
        hand = "LEFT" if node == 1 else "RIGHT"
        print(f"[HAPTIC SENT] id={action_id} P{player} {hand} "
              f"duration={HIT_DURATION_MS} ms (no motor acknowledgement)", flush=True)


async def run_haptic_keys(feedback, stop):
    """Optional operator keys using the existing cross-platform terminal reader."""
    import asyncio
    from ai_to_visualizer_demo import KeyboardInput

    commands = asyncio.Queue(maxsize=16)
    keyboard = KeyboardInput(commands)
    player = 1
    help_text = "[HAPTIC KEYS] 1/2 select player | L left | R right | ? help | Q stop server"
    print(help_text, flush=True)
    print("[HAPTIC SELECT] P1", flush=True)
    keyboard.start()
    try:
        while True:
            key = await commands.get()
            if key == "q":
                stop.set()
                return
            if key in ("1", "2"):
                player = int(key)
                print(f"[HAPTIC SELECT] P{player}", flush=True)
            elif key in ("l", "r"):
                node = 1 if key == "l" else 2
                try:
                    await asyncio.wait_for(feedback.send_pulse(player, node), timeout=0.25)
                except Exception as error:
                    print(f"[HAPTIC ERROR] manual P{player}: {error!r}", flush=True)
            elif key == "?":
                print(help_text, flush=True)
    finally:
        keyboard.close()
