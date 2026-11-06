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
        writer = self.writers.get(player)
        if writer is None or writer.is_closing():
            print(f"[HAPTIC SKIP] id={event['attack_id']} P{player}: gateway offline", flush=True)
            return
        # The player's right gateway drives node 2 locally or forwards node 1
        # over ESP-NOW. Never queue or retry a physical effect on reconnect.
        writer.write(P.actuate(node, 1, HIT_DURATION_MS))
        await writer.drain()
        hand = "LEFT" if node == 1 else "RIGHT"
        print(f"[HAPTIC SENT] id={event['attack_id']} P{player} {hand} "
              f"duration={HIT_DURATION_MS} ms (no motor acknowledgement)", flush=True)
