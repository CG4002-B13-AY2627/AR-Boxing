"""Validate the shared CG4002 protocol-v2 schemas and golden fixtures."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


CONTRACTS = Path(__file__).resolve().parent
EXAMPLES = CONTRACTS / "examples"
SCHEMA_BY_TYPE = {
    "ClientHello": "client-hello.schema.json",
    "ServerWelcome": "server-welcome.schema.json",
    "PunchAttempt": "punch-attempt.schema.json",
    "PunchObservation": "punch-observation.schema.json",
    "PickupCheck": "pickup-check.schema.json",
    "PickupObservation": "pickup-observation.schema.json",
    "PickupResult": "pickup-result.schema.json",
    "GameEvent": "game-event.schema.json",
    "MatchState": "match-state.schema.json",
    "PlayerCommand": "player-command.schema.json",
}


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_validators() -> dict[str, Draft202012Validator]:
    validators: dict[str, Draft202012Validator] = {}
    for message_type, schema_name in SCHEMA_BY_TYPE.items():
        schema = load_json(CONTRACTS / schema_name)
        Draft202012Validator.check_schema(schema)
        validators[message_type] = Draft202012Validator(schema)
    return validators


def validate_semantics(message: dict[str, object]) -> None:
    message_type = message["type"]
    if message_type == "PunchAttempt":
        if message["source_player"] == message["target_player"]:
            raise ValueError("PunchAttempt source and target must differ")
    elif message_type == "GameEvent":
        event = message["event"]
        same_player = message["source_player"] == message["target_player"]
        if event == "PUNCH" and same_player:
            raise ValueError("PUNCH source and target must differ")
        if event == "ITEM_PICKUP" and not same_player:
            raise ValueError("ITEM_PICKUP source and target must be the collector")
    elif message_type == "MatchState":
        ids = [item["id"] for item in message["active_items"]]
        if len(ids) != len(set(ids)):
            raise ValueError("MatchState active item IDs must be unique")


def validate_message(
    message: dict[str, object], validators: dict[str, Draft202012Validator]
) -> None:
    message_type = message.get("type")
    if message_type not in validators:
        raise ValueError(f"unknown or missing message type: {message_type!r}")
    validators[message_type].validate(message)
    validate_semantics(message)


class GoldenContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validators = build_validators()
        cls.fixtures = {
            path.name: load_json(path) for path in sorted(EXAMPLES.glob("*.json"))
        }

    def test_every_golden_fixture_validates(self) -> None:
        self.assertTrue(self.fixtures, "No golden fixtures found")
        for name, fixture in self.fixtures.items():
            with self.subTest(fixture=name):
                validate_message(fixture, self.validators)

    def test_every_message_type_has_a_golden_fixture(self) -> None:
        fixture_types = {fixture.get("type") for fixture in self.fixtures.values()}
        self.assertEqual(fixture_types, set(SCHEMA_BY_TYPE))

    def test_schemas_reject_unknown_fields(self) -> None:
        fixture = deepcopy(self.fixtures["client-hello.json"])
        fixture["unexpected"] = True
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_pickup_observation_requires_distance_only_when_available(self) -> None:
        available = deepcopy(self.fixtures["pickup-observation.json"])
        del available["observed_distance_m"]
        with self.assertRaises(ValidationError):
            validate_message(available, self.validators)
        unavailable = deepcopy(self.fixtures["pickup-observation-unavailable.json"])
        unavailable["observed_distance_m"] = 0
        with self.assertRaises(ValidationError):
            validate_message(unavailable, self.validators)

    def test_pickup_event_can_report_zero_gain_but_spawn_cannot(self) -> None:
        event = deepcopy(self.fixtures["game-event-item-pickup.json"])
        event["magnitude"] = 0
        validate_message(event, self.validators)
        state = deepcopy(self.fixtures["match-state-items.json"])
        state["active_items"][0]["magnitude"] = 0
        with self.assertRaises(ValidationError):
            validate_message(state, self.validators)

    def test_blocked_punch_requires_authoritative_damage(self) -> None:
        fixture = deepcopy(self.fixtures["game-event-blocked-punch.json"])
        del fixture["damage"]
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_missed_punch_cannot_deal_damage(self) -> None:
        fixture = deepcopy(self.fixtures["game-event.json"])
        fixture["outcome"] = "MISS"
        fixture["damage"] = 1.0
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_attack_multiplier_requires_duration(self) -> None:
        fixture = deepcopy(self.fixtures["match-state-items.json"])
        attack_item = fixture["active_items"][2]
        attack_item["effect_duration_ms"] = 0
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_duplicate_item_ids_are_rejected(self) -> None:
        fixture = deepcopy(self.fixtures["match-state-items.json"])
        fixture["active_items"][1]["id"] = fixture["active_items"][0]["id"]
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_message(fixture, self.validators)

    def test_punch_participants_must_differ(self) -> None:
        fixture = deepcopy(self.fixtures["punch-attempt.json"])
        fixture["target_player"] = fixture["source_player"]
        with self.assertRaisesRegex(ValueError, "differ"):
            validate_message(fixture, self.validators)

    def test_rejected_pickup_cannot_claim_accepted_reason(self) -> None:
        fixture = deepcopy(self.fixtures["pickup-result-rejected.json"])
        fixture["reason"] = "ACCEPTED"
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_only_match_end_can_carry_a_decided_result(self) -> None:
        fighting = deepcopy(self.fixtures["match-state.json"])
        fighting["match_result"] = "PENDING"
        validate_message(fighting, self.validators)
        for result in ("P1_WIN", "P2_WIN", "DRAW"):
            fighting["match_result"] = result
            with self.assertRaises(ValidationError):
                validate_message(fighting, self.validators)

        ended = deepcopy(self.fixtures["match-state-match-end.json"])
        for result in ("PENDING", "P1_WIN", "P2_WIN", "DRAW"):
            ended["match_result"] = result
            validate_message(ended, self.validators)
        del ended["match_result"]
        validate_message(ended, self.validators)

    def test_unknown_match_result_is_rejected(self) -> None:
        fixture = deepcopy(self.fixtures["match-state-match-end.json"])
        fixture["match_result"] = "p1_win"
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)


    def test_player_command_rejects_unknown_command(self) -> None:
        fixture = deepcopy(self.fixtures["player-command.json"])
        for command in ("READY", "UNREADY", "CALIBRATED", "PAUSE", "RESUME"):
            fixture["command"] = command
            validate_message(fixture, self.validators)
        for command in ("REMATCH", "ready", "HIT"):
            fixture["command"] = command
            with self.assertRaises(ValidationError):
                validate_message(fixture, self.validators)

    def test_player_command_requires_an_idempotency_id(self) -> None:
        fixture = deepcopy(self.fixtures["player-command.json"])
        del fixture["command_id"]
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)
        fixture = deepcopy(self.fixtures["player-command.json"])
        fixture["command_id"] = "-bad"
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_lobby_fields_are_optional_and_typed(self) -> None:
        legacy = deepcopy(self.fixtures["match-state-lobby.json"])
        for player in ("player_1", "player_2"):
            del legacy[player]["connected"]
            del legacy[player]["ready"]
        del legacy["phase_remaining_ms"]
        validate_message(legacy, self.validators)

        fixture = deepcopy(self.fixtures["match-state-lobby.json"])
        fixture["player_2"]["ready"] = "yes"
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)

    def test_phase_remaining_is_bounded(self) -> None:
        fixture = deepcopy(self.fixtures["match-state-countdown.json"])
        for value in (-1, 600001, 2.5):
            fixture["phase_remaining_ms"] = value
            with self.assertRaises(ValidationError):
                validate_message(fixture, self.validators)

    def test_welcome_command_support_is_optional_boolean(self) -> None:
        validate_message(deepcopy(self.fixtures["server-welcome.json"]), self.validators)
        fixture = deepcopy(self.fixtures["server-welcome-player-commands.json"])
        fixture["supports_player_commands"] = 1
        with self.assertRaises(ValidationError):
            validate_message(fixture, self.validators)


if __name__ == "__main__":
    unittest.main()
