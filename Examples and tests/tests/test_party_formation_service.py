"""Offline Option A regressions: production protocol, fake clock/game/queue only.

Run with python -B. No embedded runtime imports, live clients, or settings writes.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
import unittest
import ast
import ctypes
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Py4GWCoreLib/GlobalCache/shared_memory_src'
PACKAGE = '_formation_regression'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(SOURCE)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + '.PartyFormation', SOURCE / 'PartyFormation.py')
assert spec and spec.loader
pf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pf
spec.loader.exec_module(pf)


class MemoryTable(pf.FormationTable):
    def __init__(self) -> None:
        self.records: dict[int, Any] = {}

    @contextmanager
    def edit(self) -> Iterator[dict[int, Any]]:
        # Exercise the actual wire decoder on every read, as the production mapping does.
        records = {slot: pf.decode_record(json.dumps(asdict(row)).encode()) for slot, row in self.records.items()}
        yield records
        self.records = copy.deepcopy(records)


class World:
    def __init__(self, count: int = 2) -> None:
        self.time = 10000
        self.table = MemoryTable()
        self.runtimes = [FakeRuntime(self, index) for index in range(count)]
        self.services = [pf.FormationService(runtime, self.table) for runtime in self.runtimes]
        self.owners = [object() for _ in self.runtimes]
        self.sends: list[tuple[int, int]] = []
        self.identities_available = True
        self.advance()

    def advance(self, milliseconds: int = 200) -> None:
        self.time += milliseconds
        for service, owner in zip(self.services, self.owners):
            service.tick(owner)

    def drain(self, index: int) -> None:
        runtime = self.runtimes[index]
        queue, runtime.actions = runtime.actions, []
        for callback in queue:
            callback(lambda login: self.send(index, login))

    def send(self, sender: int, login: int) -> bool:
        self.sends.append((sender, login))
        receiver = next(runtime for runtime in self.runtimes if runtime.state.identity.login == login)
        # Native invitation acknowledgement is independent of the sidecar.
        receiver.state = replace(receiver.state, incoming=(self.runtimes[sender].state.roster,))
        return True

    def grant(self) -> None:
        self.services[0].request()
        self.advance()
        self.advance()

    def primary(self) -> None:
        self.grant()
        self.drain(0)
        self.advance()

    def joined(self, receiver: int = 1) -> None:
        roster = self.runtimes[0].state.roster + (self.runtimes[receiver].state.identity.login,)
        self.runtimes[0].state = replace(self.runtimes[0].state, roster=roster)
        self.runtimes[receiver].state = replace(self.runtimes[receiver].state, roster=roster)


class FakeRuntime:
    def __init__(self, world: World, index: int) -> None:
        self.world = world
        self.index = index
        identity = pf.Identity(
            index, f'account{index}@test', f'Character {index}', 100 + index, 200 + index, 300 + index, (226, 4, 1, 0)
        )
        self.state = pf.Snapshot(identity, 'world-instance', 1000, (identity.login,), 0, 0, 0, 8, ())
        self.policy = pf.Consent(index != 0, ('account0@test',), 1)
        self.actions: list[Callable[[Callable[[int], bool]], None]] = []
        self.ready = True
        self.pending = ''

    def now(self) -> int:
        return self.world.time

    def identities(self) -> tuple[Any, ...]:
        return (
            tuple(runtime.state.identity for runtime in self.world.runtimes) if self.world.identities_available else ()
        )

    def consent(self) -> Any:
        return self.policy

    def pending_attempt(self) -> str:
        return self.pending

    def set_pending_attempt(self, expected: str, request: str) -> None:
        if self.pending != expected:
            raise RuntimeError('attempt already owned')
        self.pending = request

    def snapshot(self) -> Any:
        if not self.ready:
            return None
        return replace(self.state, seen=tuple(identity.key for identity in self.identities()))

    def queue(self, callback: Callable[[Callable[[int], bool]], None]) -> None:
        self.actions.append(callback)


class FormationTests(unittest.TestCase):
    def test_native_exception_retains_ownership_and_stops_batch(self) -> None:
        for side_effect in (False, True):
            world = World(3)
            world.grant()
            action = world.runtimes[0].actions.pop()

            def uncertain_native(login: int) -> bool:
                if side_effect:
                    world.send(0, login)
                raise RuntimeError('native result unavailable')

            action(uncertain_native)
            for _ in range(60):
                world.advance()
                world.drain(0)
                world.drain(2)
            self.assertEqual(world.sends, [(0, 201)] if side_effect else [])
            self.assertTrue(world.runtimes[0].pending)
            self.assertTrue(world.runtimes[1].pending)

    def test_success_keeps_resolution_metadata_until_receiver_acknowledges(self) -> None:
        world = World(3)
        world.primary()
        world.drain(1)
        original = world.table.records[0].transaction.request
        world.joined()
        world.time += 200
        # Receiver publishes membership before the leader's matching publication.
        world.services[1].tick(world.owners[1])
        world.services[0].tick(world.owners[0])
        self.assertEqual(world.table.records[0].transaction.request, original)
        self.assertEqual(world.runtimes[0].pending, original)
        self.assertEqual(world.runtimes[1].pending, original)
        world.advance()
        world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertNotEqual(world.table.records[0].transaction.request, original)

    def test_international_real_mapping_repeated_reads_and_expiry(self) -> None:
        with patch.object(pf, 'TABLE_NAME', 'Py4GW_FormationInternational_' + uuid4().hex):
            table = pf.FormationTable()
            world = World(3)
            for runtime in world.runtimes[:2]:
                runtime.state = replace(
                    runtime.state, identity=replace(runtime.state.identity, location=(226, -2, 1, 0))
                )
            world.table = table
            for service in world.services:
                service.table = table
            try:
                world.advance()
                world.grant()
                for _ in range(60):
                    world.advance()
                    with table.edit() as rows:
                        self.assertEqual(rows[0].state.identity.location, (226, -2, 1, 0))
                        self.assertEqual(rows[2].state.identity.email, 'account2@test')
                self.assertEqual(world.runtimes[1].pending, '', 'expired, never-prepared grant releases ownership')
                self.assertEqual(world.sends, [])
                with table.edit() as rows:
                    del rows[1]
                with table.edit() as rows:
                    self.assertEqual(set(rows), {0, 2})
            finally:
                if table._shm is not None:
                    table._shm.close()

    def test_invalid_locations_cannot_poison_real_mapping(self) -> None:
        with patch.object(pf, 'TABLE_NAME', 'Py4GW_FormationInvalid_' + uuid4().hex):
            table = pf.FormationTable()
            row = World().table.records[0]
            invalid = [
                (226, -1, 1, 0),
                (226, -3, 1, 0),
                (226, 255, 1, 0),
                (-2, 0, 1, 0),
                (226, 0, -2, 0),
                (226, 0, 1, -2),
                (226, False, 1, 0),
                (226, 0, 1, 7),
                (226, 0, 0, 0),
            ]
            try:
                with table.edit() as rows:
                    rows[0] = row
                for location in invalid:
                    with self.subTest(location=location):
                        with self.assertRaises(ValueError):
                            with table.edit() as rows:
                                rows[0].state = replace(
                                    row.state, identity=replace(row.state.identity, location=location)
                                )
                        with table.edit() as rows:
                            self.assertEqual(rows[0], row)
            finally:
                if table._shm is not None:
                    table._shm.close()

    def test_competitor_cannot_dispatch_after_grant_or_request_expiry(self) -> None:
        world = World(3)
        world.runtimes[1].policy = pf.Consent(True, ('account0@test', 'account2@test'), 1)
        world.primary()
        world.drain(1)
        first_request = world.table.records[0].transaction.request
        for elapsed in (16, 45):
            for _ in range(elapsed):
                world.advance()
            world.services[2].request()
            for _ in range(8):
                world.advance()
                world.drain(2)
                world.drain(1)
            self.assertEqual(world.sends, [(0, 201), (1, 200)], 'expired permission is not released ownership')
            self.assertEqual(world.runtimes[1].pending, first_request)
        self.assertIn(world.table.records[0].transaction.stage, ('expired', 'failed'))

    def test_late_confirmed_membership_resolves_ownership_without_resending(self) -> None:
        world = World()
        world.primary()
        world.drain(1)
        for _ in range(60):
            world.advance()
        self.assertTrue(world.runtimes[0].pending)
        self.assertTrue(world.runtimes[1].pending)
        world.joined()
        world.advance()
        world.advance()
        self.assertEqual([runtime.pending for runtime in world.runtimes], ['', ''])
        self.assertEqual(world.table.records[0].transaction.stage, 'confirmed')
        self.assertEqual(world.sends, [(0, 201), (1, 200)])

    def test_revocation_releases_only_never_prepared_attempt(self) -> None:
        for dispatched in (False, True):
            world = World()
            world.grant()
            if dispatched:
                world.drain(0)
            world.services[1].invalidate_consent()
            world.runtimes[1].policy = pf.Consent()
            for _ in range(6):
                world.advance()
            world.drain(0)
            world.drain(1)
            self.assertEqual(bool(world.runtimes[1].pending), dispatched)
            self.assertEqual(len(world.sends), int(dispatched))

    def test_reload_reconnect_or_total_mapping_loss_does_not_release_uncertainty(self) -> None:
        for loss in ('reload', 'reconnect', 'mapping'):
            world = World(3)
            world.runtimes[1].policy = pf.Consent(True, ('account0@test', 'account2@test'), 1)
            world.primary()
            world.drain(1)
            request = world.runtimes[1].pending
            if loss == 'reconnect':
                world.runtimes[1].ready = False
                world.advance()
                world.runtimes[1].ready = True
                state = world.runtimes[1].state
                world.runtimes[1].state = replace(state, identity=replace(state.identity, hwnd=999))
            if loss == 'mapping':
                world.table = MemoryTable()
            world.time += 1
            world.services = [pf.FormationService(runtime, world.table) for runtime in world.runtimes]
            world.advance()
            self.assertIn('unresolved', world.services[0].request())
            world.services[2].request()
            for _ in range(60):
                world.advance()
                world.drain(0)
                world.drain(1)
                world.drain(2)
            self.assertEqual(world.runtimes[1].pending, request, loss)
            self.assertEqual(world.sends, [(0, 201), (1, 200)], loss)

    def test_flush_failure_stops_batch_with_and_without_local_execution_ledger(self) -> None:
        for restart in (False, True):
            world = World(3)
            world.grant()
            action = world.runtimes[0].actions.pop()
            original_edit = world.table.edit

            @contextmanager
            def fail_after_native() -> Iterator[dict[int, Any]]:
                with original_edit() as rows:
                    yield rows
                    if world.sends:
                        raise OSError('flush failed after native call')

            with patch.object(world.table, 'edit', fail_after_native):
                with self.assertRaises(OSError):
                    action(lambda login: world.send(0, login))
            self.assertTrue(world.table.records[0].transaction.leader_prepared)
            self.assertFalse(world.table.records[0].transaction.leader_dispatched)
            if restart:
                world.time += 1
                world.services[0] = pf.FormationService(world.runtimes[0], world.table)
            world.runtimes[1].ready = False
            for _ in range(60):
                world.advance()
                world.drain(0)
                world.drain(2)
            self.assertEqual(world.sends, [(0, 201)], f'no automatic second receiver, restart={restart}')
            self.assertTrue(world.runtimes[0].pending)
            self.assertIn('unresolved', world.services[0].request())

    def test_preparation_flush_failure_and_final_validation_send_nothing(self) -> None:
        world = World()
        world.grant()
        action = world.runtimes[0].actions.pop()
        original_edit = world.table.edit

        @contextmanager
        def failed_prepare() -> Iterator[dict[int, Any]]:
            with original_edit() as rows:
                yield rows
                raise OSError('write-ahead flush failed')

        with patch.object(world.table, 'edit', failed_prepare):
            with self.assertRaises(OSError):
                action(lambda login: world.send(0, login))
        self.assertEqual(world.sends, [])
        self.assertTrue(world.runtimes[0].pending, 'uncertainty must remain blocked')
        other = World()
        other.grant()
        original_save = other.runtimes[0].set_pending_attempt

        def slow_save(expected: str, request: str) -> None:
            original_save(expected, request)
            other.time += pf.GRANT_MS

        with patch.object(other.runtimes[0], 'set_pending_attempt', slow_save):
            other.drain(0)
        self.assertEqual(other.sends, [], 'write-ahead save delay must not bypass final freshness validation')

    def test_candidate_order_preserves_heroai_profession_priority(self) -> None:
        world = World(7)
        for runtime, profession in zip(world.runtimes[1:], (3, 8, 4, 9, 5, 1)):
            runtime.state = replace(runtime.state, profession=profession)
        world.advance()
        world.services[0].request()
        self.assertEqual(
            [item[2] for item in world.services[0]._pending], [f'Character {index}' for index in range(6, 0, -1)]
        )

    def test_mapping_flush_failure_cannot_replay_native_invitation(self) -> None:
        world = World()
        world.grant()
        action = world.runtimes[0].actions.pop()
        original_edit = world.table.edit

        @contextmanager
        def failed_flush() -> Iterator[dict[int, Any]]:
            with original_edit() as rows:
                yield rows
                if world.sends:
                    raise OSError('simulated mapping flush failure after native dispatch')

        with patch.object(world.table, 'edit', failed_flush):
            with self.assertRaises(OSError):
                action(lambda login: world.send(0, login))
        action(lambda login: world.send(0, login))
        self.assertEqual(world.sends, [(0, 201)])

    def test_every_location_component_and_endpoint_identity_is_bound(self) -> None:
        for component in range(4):
            world = World()
            world.primary()
            state = world.runtimes[1].state
            location = list(state.identity.location)
            location[component] += 1
            world.runtimes[1].state = replace(state, identity=replace(state.identity, location=tuple(location)))
            world.drain(1)
            self.assertEqual(len(world.sends), 1, f'location component {component}')
        for change in ({'slot': 4}, {'hwnd': 999}, {'login': 999}, {'agent': 999}, {'email': 'other@test'}):
            world = World()
            world.primary()
            state = world.runtimes[1].state
            world.runtimes[1].state = replace(state, identity=replace(state.identity, **change))
            world.drain(1)
            self.assertEqual(len(world.sends), 1, change)

    def test_immediate_local_revocation_invalidates_both_queued_endpoints(self) -> None:
        world = World()
        world.grant()
        world.services[1].invalidate_consent()
        world.drain(0)
        self.assertEqual(world.sends, [])

    def test_native_failure_is_failed_and_never_queued_success(self) -> None:
        world = World()
        world.grant()
        action = world.runtimes[0].actions.pop()
        action(lambda login: False)
        self.assertEqual(world.table.records[0].transaction.stage, 'failed')

    def test_real_mapping_roundtrip_and_incompatible_header_fail_closed(self) -> None:
        with patch.object(pf, 'TABLE_NAME', 'Py4GW_FormationRegression_' + uuid4().hex):
            table = pf.FormationTable()
            world = World()
            try:
                with table.edit() as rows:
                    rows[0] = world.table.records[0]
                with table.edit() as rows:
                    self.assertEqual(rows[0], world.table.records[0])
                table._shm.buf[0] = 0
                with self.assertRaisesRegex(RuntimeError, 'incompatible'):
                    with table.edit():
                        self.fail('must refuse incompatible mapping')
            finally:
                if table._shm is not None:
                    table._shm.close()

    def test_actual_terminal_partycache_dispatch_has_one_queue_hop(self) -> None:
        tree = ast.parse((ROOT / 'Py4GWCoreLib/GlobalCache/PartyCache.py').read_text(encoding='utf-8-sig'))
        node = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'QueueFormationInvite'
        )
        node.decorator_list = []
        namespace: dict[str, Any] = {}
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])), 'PartyCache.py', 'exec'
            ),
            namespace,
        )
        queued: list[Callable[[], None]] = []
        native: list[int] = []

        def native_invite(login: int) -> bool:
            native.append(login)
            return True

        def enqueue(name: str, action: Callable[[], None]) -> None:
            queued.append(action)

        parent = SimpleNamespace(
            _party_instance=SimpleNamespace(InvitePlayer=native_invite),
            _action_queue_manager=SimpleNamespace(AddAction=enqueue),
        )
        state = {'allowed': True}

        def dispatch(invite: Callable[[int], bool]) -> None:
            if state['allowed']:
                invite(123)

        namespace['QueueFormationInvite'](SimpleNamespace(_parent=parent), dispatch)
        self.assertEqual(native, [])
        self.assertEqual(len(queued), 1)
        state['allowed'] = False
        queued.pop()()
        self.assertEqual(native, [])
        self.assertEqual(queued, [])

    def test_messaging_runs_ordinary_processing_when_service_fails(self) -> None:
        source = ast.parse((ROOT / 'Py4GWCoreLib/GlobalCache/SharedMemory.py').read_text(encoding='utf-8-sig'))
        tick = next(
            node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == 'TickPartyFormation'
        )
        namespace: dict[str, Any] = {}
        exec(compile(ast.Module(body=[tick], type_ignores=[]), 'SharedMemory.py', 'exec'), namespace)
        calls: list[str] = []

        def unavailable() -> None:
            raise RuntimeError('mapping unavailable')

        manager = SimpleNamespace(GetPartyFormation=unavailable, _party_formation=None)
        tick_function = namespace['TickPartyFormation']

        def tick_service(owner: object) -> None:
            tick_function(manager, owner)

        def heal(email: str) -> None:
            calls.append('heal')

        manager.TickPartyFormation = tick_service
        source = ast.parse((ROOT / 'Widgets/System/Messaging.py').read_text(encoding='utf-8-sig'))
        main = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        namespace: dict[str, Any] = dict(
            GLOBAL_CACHE=SimpleNamespace(ShMem=manager),
            _FORMATION_MESSAGING_LIFETIME=object(),
            Player=SimpleNamespace(GetAccountEmail=lambda: 'account@test'),
            HealStaleHeroAISnapshot=heal,
            _process_pending_widget_enables=lambda: calls.append('enable'),
            ProcessMessages=lambda: calls.append('messages'),
        )
        exec(compile(ast.Module(body=[main], type_ignores=[]), 'Messaging.py', 'exec'), namespace)
        namespace['main']()
        self.assertEqual(calls, ['heal', 'enable', 'messages'])

    def test_default_off_and_wrong_named_leader_deny(self) -> None:
        for policy in (pf.Consent(), pf.Consent(True, ('someone_else@test',), 1)):
            with self.subTest(policy=policy):
                world = World()
                world.runtimes[1].policy = policy
                world.advance()
                world.grant()
                world.drain(0)
                world.drain(1)
                self.assertEqual(world.sends, [])
                self.assertEqual(world.table.records[0].transaction.stage, 'denied')

    def test_request_challenge_commit_then_confirmed_membership(self) -> None:
        world = World()
        world.primary()
        tx = world.table.records[0].transaction
        self.assertTrue(tx.challenge)
        self.assertEqual(tx.stage, 'waiting')
        self.assertEqual(world.sends, [(0, 201)])
        world.drain(1)
        self.assertEqual(world.sends, [(0, 201), (1, 200)])
        self.assertNotEqual(world.table.records[0].transaction.stage, 'confirmed')
        world.joined()
        world.advance()
        world.advance()
        self.assertEqual(world.table.records[0].transaction.stage, 'confirmed')

    def test_repeated_click_does_not_extend_or_duplicate(self) -> None:
        world = World()
        world.grant()
        original = copy.deepcopy(world.table.records[0].transaction)
        for _ in range(5):
            world.services[0].request()
        self.assertEqual(world.table.records[0].transaction, original)
        world.drain(0)
        world.drain(0)
        self.assertEqual(world.sends, [(0, 201)])

    def test_replayed_queued_callback_is_single_use(self) -> None:
        world = World()
        world.grant()
        action = world.runtimes[0].actions[0]
        action(lambda login: world.send(0, login))
        action(lambda login: world.send(0, login))
        self.assertEqual(world.sends, [(0, 201)])

    def test_grant_expiry_blocks_terminal_call(self) -> None:
        world = World()
        world.grant()
        world.time += pf.GRANT_MS
        world.drain(0)
        self.assertEqual(world.sends, [])

    def test_consent_revoked_while_receiver_queued(self) -> None:
        world = World()
        world.primary()
        world.runtimes[1].policy = pf.Consent(False, (), 2)
        world.drain(1)
        self.assertEqual(world.sends, [(0, 201)])
        self.assertEqual(world.table.records[0].transaction.stage, 'denied')

    def test_revoke_then_restore_does_not_reuse_grant(self) -> None:
        world = World()
        world.primary()
        world.runtimes[1].policy = replace(world.runtimes[1].policy, revision=3)
        world.drain(1)
        self.assertEqual(len(world.sends), 1)

    def test_receiver_party_changes_before_terminal_execution(self) -> None:
        for change in ({'roster': (201, 999)}, {'heroes': 1}, {'henchmen': 1}, {'others': 1}):
            with self.subTest(change=change):
                world = World()
                world.primary()
                world.runtimes[1].state = replace(world.runtimes[1].state, **change)
                world.drain(1)
                self.assertEqual(world.sends, [(0, 201)])

    def test_initial_non_solo_rejection(self) -> None:
        for change in ({'roster': (201, 999)}, {'heroes': 1}, {'henchmen': 1}):
            world = World()
            world.runtimes[1].state = replace(world.runtimes[1].state, **change)
            world.advance()
            world.grant()
            world.drain(0)
            self.assertEqual(world.sends, [], change)

    def test_leader_capacity_and_leadership_change_at_dispatch(self) -> None:
        for change in ({'capacity': 1}, {'roster': (999, 200)}, {'heroes': 1}):
            world = World()
            world.grant()
            world.runtimes[0].state = replace(world.runtimes[0].state, **change)
            world.drain(0)
            self.assertEqual(world.sends, [], change)

    def test_multiple_receivers_are_serialized_without_overbooking(self) -> None:
        world = World(3)
        world.runtimes[0].state = replace(world.runtimes[0].state, capacity=2)
        world.advance()
        world.primary()
        world.drain(1)
        world.joined()
        for _ in range(4):
            world.advance()
            for index in range(3):
                world.drain(index)
        self.assertEqual(world.sends, [(0, 201), (1, 200)])

    def test_instance_location_or_mutual_identity_mismatch(self) -> None:
        for change in (
            {'instance': 'other-world'},
            {'identity': pf.Identity(1, 'account1@test', 'Character 1', 101, 201, 301, (226, 4, 2, 0))},
        ):
            world = World()
            world.runtimes[1].state = replace(world.runtimes[1].state, **change)
            world.advance()
            world.grant()
            world.drain(0)
            self.assertEqual(world.sends, [], change)

    def test_queued_character_change(self) -> None:
        world = World()
        world.primary()
        old = world.runtimes[1].state
        world.runtimes[1].state = replace(old, identity=replace(old.identity, character='New character'))
        world.drain(1)
        self.assertEqual(len(world.sends), 1)

    def test_reload_reconnect_and_long_pause_invalidate_old_work(self) -> None:
        for kind in ('reload', 'reconnect', 'pause'):
            world = World()
            world.grant()
            if kind == 'reload':
                world.owners[0] = object()
            elif kind == 'reconnect':
                world.runtimes[0].state = replace(world.runtimes[0].state, uptime=1)
            else:
                world.time += 1000
            world.advance()
            world.drain(0)
            self.assertEqual(world.sends, [], kind)

    def test_stale_future_missing_and_duplicate_publications(self) -> None:
        for mode in ('stale', 'future', 'missing', 'duplicate'):
            world = World()
            world.grant()
            if mode == 'stale':
                world.table.records[1].sampled = world.time - 1000
            elif mode == 'future':
                world.table.records[1].sampled = world.time + 1000
            elif mode == 'missing':
                world.identities_available = False
            else:
                row = copy.deepcopy(world.table.records[1])
                row.session = 'duplicate-session'
                world.table.records[2] = row
            world.drain(0)
            self.assertEqual(world.sends, [], mode)

    def test_receiver_requires_actual_matching_incoming_invite(self) -> None:
        world = World()
        world.grant()
        world.drain(0)
        world.runtimes[1].state = replace(world.runtimes[1].state, incoming=((999,),))
        world.advance()
        world.drain(1)
        self.assertEqual(world.sends, [(0, 201)])

    def test_competing_leaders_receive_only_one_grant(self) -> None:
        world = World(3)
        world.runtimes[1].policy = pf.Consent(True, ('account0@test', 'account2@test'), 1)
        world.runtimes[2].policy = pf.Consent()
        world.advance()
        world.services[0].request()
        world.services[2].request()
        for _ in range(4):
            world.advance()
            world.drain(0)
            world.drain(2)
        self.assertLessEqual(sum(login == 201 for _, login in world.sends), 1)

    def test_wrong_resulting_leadership_never_reports_confirmed(self) -> None:
        world = World()
        world.primary()
        world.drain(1)
        for runtime in world.runtimes:
            runtime.state = replace(runtime.state, roster=(201, 200))
        world.advance()
        world.advance()
        self.assertNotEqual(world.table.records[0].transaction.stage, 'confirmed')

    def test_decode_rejects_malformed_transaction_and_consent(self) -> None:
        world = World()
        for field, value in (('consent', {'enabled': 'true'}), ('transaction', {'command': 'travel'})):
            data = asdict(world.table.records[0])
            data[field] = value
            with self.assertRaises((KeyError, ValueError)):
                pf.decode_record(json.dumps(data).encode())


class CancellationTests(unittest.TestCase):
    def test_both_queue_delay_variants_with_actual_windows_mapping(self) -> None:
        for count in (2, 3):
            with self.subTest(accounts=count), patch.object(pf, 'TABLE_NAME', 'Py4GW_CancellationFlow_' + uuid4().hex):
                world = World(count)
                table = pf.FormationTable()
                try:
                    with table.edit() as rows:
                        rows.update(world.table.records)
                    for service in world.services:
                        service.table = table
                    world.grant()
                    queued_at = world.time
                    obsolete = world.runtimes[0].actions.pop()
                    with table.edit() as rows:
                        request = rows[0].transaction.request
                        expires = rows[0].transaction.grant_expires
                    while world.time + 200 < expires:
                        world.advance()
                    world.time += 200
                    world.services[0].tick(world.owners[0])
                    if count == 2:
                        self.assertIn('acknowledgement', world.services[0].request())
                    with table.edit() as rows:
                        self.assertEqual(rows[0].transaction.request, request)
                        self.assertIsNone(rows[0].transaction.cancellation_ack)
                    self.assertEqual(world.runtimes[1].pending, request)
                    while world.time < queued_at + 3200:
                        world.advance()
                    for _ in range(65):
                        world.advance()
                        for index in range(count):
                            world.drain(index)
                    self.assertEqual(world.runtimes[1].pending, '')
                    before = list(world.sends)
                    obsolete(lambda login: world.send(0, login))
                    self.assertEqual(world.sends, before)
                    self.assertEqual(world.sends, [] if count == 2 else [(0, 202), (2, 200)])
                finally:
                    if table._shm is not None:
                        table._shm.close()

    def test_failed_intent_publication_does_not_clear_marker(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        original = world.table.edit

        @contextmanager
        def failed_intent() -> Iterator[dict[int, Any]]:
            with original() as rows:
                yield rows
                raise OSError('cancellation intent publication failed')

        with patch.object(world.table, 'edit', failed_intent):
            with self.assertRaises(OSError):
                world.services[1].tick(world.owners[1])
        self.assertEqual(world.runtimes[1].pending, request)
        self.assertIsNone(world.table.records[0].transaction.cancellation_intent)
        self.assertIsNone(world.table.records[0].transaction.cancellation_ack)
        for _ in range(5):
            world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        world.drain(0)
        self.assertEqual(world.sends, [])

    def test_leader_identity_replacement_keeps_receiver_cleanup_evidence(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        state = world.runtimes[0].state
        world.runtimes[0].state = replace(state, identity=replace(state.identity, email='replacement@test'))
        world.time += 200
        world.services[0].tick(world.owners[0])
        self.assertEqual(world.table.records[0].transaction.request, request)
        for _ in range(5):
            world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        world.drain(0)
        self.assertEqual(world.sends, [])

    def expire_leader_only(self, world: World) -> str:
        tx = world.table.records[0].transaction
        request = tx.request
        while world.time + 200 < tx.grant_expires:
            world.advance()
        world.time += 200
        world.services[0].tick(world.owners[0])
        return request

    def test_exact_two_receiver_queue_delay_retains_evidence_until_ack(self) -> None:
        world = World(3)
        world.grant()
        started = world.time
        request = self.expire_leader_only(world)
        self.assertEqual(world.table.records[0].transaction.request, request)
        self.assertEqual(world.runtimes[1].pending, request)
        world.services[1].tick(world.owners[1])
        self.assertIsNotNone(world.table.records[0].transaction.cancellation_intent)
        self.assertIsNone(world.table.records[0].transaction.cancellation_ack)
        self.assertEqual(world.runtimes[1].pending, request, 'intent must commit before clearing')
        while world.time < started + 3200:
            world.advance()
        for _ in range(65):
            world.advance()
            for index in range(3):
                world.drain(index)
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertNotIn('evidence unavailable', world.services[1].status)
        self.assertEqual(world.sends, [(0, 202), (2, 200)])

    def test_immediate_fresh_click_and_obsolete_callback_after_new_request(self) -> None:
        world = World()
        world.grant()
        obsolete = world.runtimes[0].actions.pop()
        request = self.expire_leader_only(world)
        self.assertIn('acknowledgement', world.services[0].request())
        self.assertEqual(world.table.records[0].transaction.request, request)
        obsolete(lambda login: world.send(0, login))
        self.assertEqual(world.sends, [])
        for _ in range(5):
            world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertEqual(world.services[0].request(), 'requested')
        world.advance()
        world.advance()
        self.assertNotEqual(world.table.records[0].transaction.request, request)
        obsolete(lambda login: world.send(0, login))
        self.assertEqual(world.sends, [])
        world.drain(0)
        world.advance()
        world.drain(1)
        self.assertEqual(world.sends, [(0, 201), (1, 200)])

    def test_delayed_ack_blocks_batch_clicks_and_competing_leader(self) -> None:
        world = World(3)
        world.runtimes[1].policy = pf.Consent(True, ('account0@test', 'account2@test'), 1)
        world.grant()
        request = self.expire_leader_only(world)
        world.services[2].request()
        for _ in range(25):
            world.time += 200
            world.services[0].tick(world.owners[0])
            world.services[2].tick(world.owners[2])
            world.services[0].request()
            world.drain(0)
            world.drain(2)
            self.assertEqual(world.table.records[0].transaction.request, request)
            self.assertEqual(world.runtimes[1].pending, request)
            self.assertEqual(world.sends, [])
        for _ in range(6):
            world.advance()
        self.assertNotEqual(world.runtimes[1].pending, request)

    def test_wrong_stale_and_out_of_order_acknowledgements_are_rejected(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        world.services[1].tick(world.owners[1])
        tx = world.table.records[0].transaction
        binding = world.services[1]._cancellation_binding(tx, world.services[1].session)
        with world.table.edit() as rows:
            rows[0].transaction.cancellation_ack = binding
        self.assertIn('acknowledgement', world.services[0].request(), 'out-of-order ack cannot precede marker clearing')
        world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        for index in range(6):
            bad = list(binding)
            bad[index] = 'unrelated-binding'
            with world.table.edit() as rows:
                rows[0].transaction.cancellation_ack = tuple(bad)
            self.assertIn('acknowledgement', world.services[0].request(), f'wrong binding component {index}')
            self.assertEqual(world.table.records[0].transaction.request, request)
        world.advance()
        self.assertEqual(world.services[0].request(), 'requested')

    def test_ack_retries_do_not_clear_twice(self) -> None:
        world = World()
        world.grant()
        self.expire_leader_only(world)
        clears: list[str] = []
        original = world.runtimes[1].set_pending_attempt

        def clearing(expected: str, request: str) -> None:
            if not request:
                clears.append(expected)
            original(expected, request)

        with patch.object(world.runtimes[1], 'set_pending_attempt', clearing):
            for _ in range(8):
                world.advance()
        self.assertEqual(len(clears), 1)
        self.assertEqual(world.sends, [])

    def test_cancellation_flush_failure_retains_marker_and_metadata(self) -> None:
        world = World()
        world.grant()
        request = world.runtimes[1].pending
        expires = world.table.records[0].transaction.grant_expires
        while world.time + 200 < expires:
            world.advance()
        world.time += 200
        original = world.table.edit

        @contextmanager
        def failed() -> Iterator[dict[int, Any]]:
            with original() as rows:
                yield rows
                raise OSError('cancellation flush failed')

        with patch.object(world.table, 'edit', failed):
            with self.assertRaises(OSError):
                world.services[0].tick(world.owners[0])
        self.assertEqual(world.table.records[0].transaction.request, request)
        self.assertEqual(world.runtimes[1].pending, request)
        for _ in range(6):
            world.advance()
        world.drain(0)
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertEqual(world.sends, [])

    def test_failed_marker_save_cannot_publish_ack(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        world.services[1].tick(world.owners[1])
        world.time += 200

        def fail_save(expected: str, request: str) -> None:
            raise OSError('safety marker save failed')

        with patch.object(world.runtimes[1], 'set_pending_attempt', fail_save):
            with self.assertRaises(OSError):
                world.services[1].tick(world.owners[1])
        self.assertEqual(world.runtimes[1].pending, request)
        self.assertIsNone(world.table.records[0].transaction.cancellation_ack)
        world.services[0].tick(world.owners[0])
        self.assertEqual(world.table.records[0].transaction.request, request)
        for _ in range(4):
            world.advance()
        self.assertEqual(world.runtimes[1].pending, '')

    def test_ack_flush_failure_retries_after_receiver_reload(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        world.services[1].tick(world.owners[1])
        world.time += 200
        original = world.table.edit

        @contextmanager
        def failed_ack() -> Iterator[dict[int, Any]]:
            with original() as rows:
                yield rows
                raise OSError('ack publication failed')

        with patch.object(world.table, 'edit', failed_ack):
            with self.assertRaises(OSError):
                world.services[1].tick(world.owners[1])
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertIsNone(world.table.records[0].transaction.cancellation_ack)
        world.services[0].tick(world.owners[0])
        self.assertEqual(world.table.records[0].transaction.request, request)
        world.time += 1
        world.services[1] = pf.FormationService(world.runtimes[1], world.table)
        for _ in range(5):
            world.advance()
        self.assertEqual(world.services[0].request(), 'requested')
        self.assertEqual(world.sends, [])

    def test_leader_reload_retains_never_prepared_cancellation(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        world.time += 1
        world.services[0] = pf.FormationService(world.runtimes[0], world.table)
        world.advance()
        self.assertEqual(world.table.records[0].transaction.request, request)
        for _ in range(4):
            world.advance()
        self.assertEqual(world.runtimes[1].pending, '')
        self.assertEqual(world.services[0].request(), 'requested')

    def test_reconnect_identity_change_cannot_ack_another_endpoint(self) -> None:
        world = World()
        world.grant()
        request = self.expire_leader_only(world)
        state = world.runtimes[1].state
        world.runtimes[1].state = replace(state, identity=replace(state.identity, hwnd=999))
        for _ in range(8):
            world.advance()
        self.assertEqual(world.table.records[0].transaction.request, request)
        self.assertEqual(world.runtimes[1].pending, request)
        self.assertIsNone(world.table.records[0].transaction.cancellation_ack)
        world.drain(0)
        self.assertEqual(world.sends, [])

    def test_cancellation_receipts_roundtrip_real_mapping_and_v2_is_rejected(self) -> None:
        world = World()
        world.grant()
        self.expire_leader_only(world)
        world.services[1].tick(world.owners[1])
        world.advance()
        with patch.object(pf, 'TABLE_NAME', 'Py4GW_CancellationRegression_' + uuid4().hex):
            table = pf.FormationTable()
            try:
                with table.edit() as rows:
                    rows.update(world.table.records)
                with table.edit() as rows:
                    self.assertEqual(
                        rows[0].transaction.cancellation_ack, world.table.records[0].transaction.cancellation_ack
                    )
                table._shm.buf[: pf._HEADER.size] = pf._HEADER.pack(b'GWFORM02', 2, pf.MAX_ACCOUNTS, pf.RECORD_BYTES)
                with self.assertRaisesRegex(RuntimeError, 'incompatible'):
                    with table.edit():
                        self.fail('v2 mapping must not be reinterpreted')
            finally:
                if table._shm is not None:
                    table._shm.close()


def load_runtime() -> Any:
    account_module = types.ModuleType(PACKAGE + '.AllAccounts')
    setattr(account_module, 'AllAccounts', object)
    runtime_spec = importlib.util.spec_from_file_location(
        PACKAGE + '.PartyFormationRuntime', SOURCE / 'PartyFormationRuntime.py'
    )
    assert runtime_spec and runtime_spec.loader
    module = importlib.util.module_from_spec(runtime_spec)
    with patch.dict(sys.modules, {account_module.__name__: account_module}):
        runtime_spec.loader.exec_module(module)
    return module


class BoundaryTests(unittest.TestCase):
    def test_owned_attempt_uses_forced_local_persistence_and_survives_adapter_reload(self) -> None:
        runtime = load_runtime()
        values: dict[str, str] = {}
        saves: list[bool] = []
        can_save = True

        class Settings:
            def __init__(self, name: str, scope: str) -> None:
                self.document = (name, scope)
                if self.document != ('HeroAI/PartyFormation.ini', 'account'):
                    raise AssertionError(self.document)

            def is_ready(self) -> bool:
                return True

            def get_str(self, section: str, key: str, default: str) -> str:
                return values.get(section + '/' + key, default)

            def set_str(self, section: str, key: str, value: str) -> None:
                values[section + '/' + key] = value

            def save(self) -> bool:
                saves.append(can_save)
                return can_save

        module = types.ModuleType('Py4GWCoreLib.py4gwcorelib_src.Settings')
        setattr(module, 'Settings', Settings)
        with patch.dict(sys.modules, {module.__name__: module}):
            source = runtime.FormationRuntime(lambda: None)
            request = uuid4().hex
            self.assertEqual(source.pending_attempt(), '')
            source.set_pending_attempt('', request)
            reloaded = load_runtime().FormationRuntime(lambda: None)
            self.assertEqual(reloaded.pending_attempt(), request)
            with self.assertRaises(RuntimeError):
                reloaded.set_pending_attempt('', uuid4().hex)
            can_save = False
            with self.assertRaises(RuntimeError):
                reloaded.set_pending_attempt(request, '')
            self.assertEqual(source.pending_attempt(), request, 'failed clearing retains evidence')
            can_save = True
            reloaded.set_pending_attempt(request, '')
            self.assertEqual(source.pending_attempt(), '')
            self.assertEqual(saves, [True, False, True])

    def test_other_occupants_uses_existing_partyinfo_storage_and_rejects_unknown(self) -> None:
        runtime = load_runtime()
        namespace: dict[str, Any] = dict(vars(ctypes))
        namespace.update(__name__='_formation_native_fixture')
        for filename in ('gw_array.py', 'gw_list.py'):
            source = ROOT / 'Py4GWCoreLib/native_src/internals' / filename
            exec(compile(source.read_text(encoding='utf-8-sig'), str(source), 'exec'), namespace)
        tree = ast.parse((ROOT / 'Py4GWCoreLib/native_src/context/PartyContext.py').read_text(encoding='utf-8-sig'))
        nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name in ('PlayerPartyMember', 'HeroPartyMember', 'HenchmanPartyMember', 'PartyInfoStruct')
        ]
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), 'PartyContext.py', 'exec'
            ),
            namespace,
        )
        party = namespace['PartyInfoStruct']()
        players = (namespace['PlayerPartyMember'] * 1)()
        players[0].login_number = 200
        players[0].state = 1
        party.party_id = 7
        party.players_array.m_buffer = ctypes.addressof(players)
        party.players_array.m_size = party.players_array.m_capacity = 1
        context = SimpleNamespace(player_party=party)
        self.assertEqual(runtime._other_occupants(context, 7, (200,)), 0)
        occupants = (ctypes.c_uint32 * 1)(123)
        party.others_array.m_buffer = ctypes.addressof(occupants)
        party.others_array.m_size = party.others_array.m_capacity = 1
        self.assertEqual(
            runtime._other_occupants(context, 7, (200,)), 1, 'populated underlying array overrides empty binding'
        )
        party.others_array.m_buffer = None
        self.assertIsNone(runtime._other_occupants(context, 7, (200,)), 'invalid array is not absence')
        self.assertIsNone(runtime._other_occupants(context, 8, (200,)), 'mismatched native snapshot')
        self.assertIsNone(runtime._other_occupants(SimpleNamespace(player_party=None), 7, (200,)))

    def test_runtime_rejects_guild_halls_and_missing_instance_evidence(self) -> None:
        runtime = load_runtime()
        char = SimpleNamespace(token1=1, host=b'instance-host')

        def messaging_enabled(name: str) -> bool:
            return name == 'Messaging'

        modules: dict[str, Any] = {
            'PyMap': SimpleNamespace(
                get_is_map_loaded=lambda: True,
                get_instance_type=lambda: 0,
                get_is_in_cinematic=lambda: False,
                get_is_observing=lambda: False,
            ),
            'PyParty': SimpleNamespace(),
            'PySystem': SimpleNamespace(),
            'Py4GWCoreLib.Context': SimpleNamespace(
                GWContext=SimpleNamespace(
                    Char=SimpleNamespace(GetContext=lambda: char),
                    InstanceInfo=lambda: SimpleNamespace(GetMapInfo=lambda: SimpleNamespace(max_party_size=8)),
                )
            ),
            'Py4GWCoreLib.enums_src.Map_enums': SimpleNamespace(
                InstanceType=SimpleNamespace(Outpost=SimpleNamespace(value=0))
            ),
            'Py4GWCoreLib.py4gwcorelib_src.WidgetManager': SimpleNamespace(
                get_widget_handler=lambda: SimpleNamespace(is_widget_enabled=messaging_enabled)
            ),
            'Py4GWCoreLib.Map': SimpleNamespace(Map=SimpleNamespace(IsGuildHall=lambda: True)),
        }
        source = runtime.FormationRuntime(lambda: None)
        with patch.dict(sys.modules, modules):
            self.assertIsNone(source.snapshot(), 'guild halls must fail closed before accessing party identity')
            char.token1 = 0
            self.assertIsNone(source.snapshot(), 'missing world identity must fail closed')

    def test_form_command_has_no_same_group_legacy_or_travel_fallback(self) -> None:
        world = World()
        world.runtimes[1].policy = pf.Consent()
        world.advance()
        tree = ast.parse((ROOT / 'Py4GWCoreLib/HeroAI/commands.py').read_text(encoding='utf-8-sig'))
        node = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '__invite_all_command'
        )
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        namespace: dict[str, Any] = dict(
            GLOBAL_CACHE=SimpleNamespace(ShMem=SimpleNamespace(GetPartyFormation=lambda: world.services[0]))
        )
        exec(
            compile(ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])), 'commands.py', 'exec'),
            namespace,
        )
        namespace['__invite_all_command'](None, [SimpleNamespace(IsolationGroupID=1, AccountEmail='account1@test')])
        world.advance()
        world.advance()
        world.drain(0)
        self.assertEqual(world.sends, [])
        self.assertEqual(world.table.records[0].transaction.stage, 'denied')

    def test_separate_travel_retains_ordinary_visible_target_selection(self) -> None:
        calls: list[tuple[Any, ...]] = []

        def record(*args: Any) -> None:
            calls.append(args)

        def log(*args: Any) -> None:
            pass

        def account(email: str, district: int) -> Any:
            return SimpleNamespace(
                AccountEmail=email,
                AgentData=SimpleNamespace(
                    CharacterName=email, Map=SimpleNamespace(MapID=226, Region=4, District=district, Language=0)
                ),
            )

        visible = [account('leader@test', 1), account('same@test', 1), account('different@test', 2)]
        namespace: dict[str, Any] = dict(
            Player=SimpleNamespace(GetAccountEmail=lambda: 'leader@test'),
            Map=SimpleNamespace(
                GetMapID=lambda: 226,
                GetRegion=lambda: (4, ''),
                GetDistrict=lambda: 1,
                GetLanguage=lambda: (0, ''),
                IsGuildHall=lambda: False,
            ),
            ConsoleLog=log,
            SharedCommandType=SimpleNamespace(TravelToMap=7, TravelToGuildHall=8),
            GLOBAL_CACHE=SimpleNamespace(ShMem=SimpleNamespace(GetAllAccountData=lambda: visible, SendMessage=record)),
        )
        tree = ast.parse((ROOT / 'Py4GWCoreLib/HeroAI/commands.py').read_text(encoding='utf-8-sig'))
        node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == '__travel_alts_to_leader_map_command'
        )
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(
            compile(ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[])), 'commands.py', 'exec'),
            namespace,
        )
        namespace[node.name](None, [account('hidden@test', 2)])
        self.assertEqual(calls, [('leader@test', 'different@test', 7, (226, 4, 1, 0))])

    def test_runtime_identity_reader_rejects_duplicate_invalid_and_future_rows(self) -> None:
        runtime = load_runtime()
        inactive = SimpleNamespace(IsAccount=False, IsSlotActive=False)

        def account(email: str, stamp: int = 10000, agent: int = 100, hwnd: int = 300) -> Any:
            return SimpleNamespace(
                IsAccount=True,
                IsSlotActive=True,
                LastUpdated=stamp,
                AccountEmail=email,
                Key=SimpleNamespace(HWND=hwnd),
                AgentData=SimpleNamespace(
                    CharacterName='Character',
                    AgentID=agent,
                    LoginNumber=200,
                    Map=SimpleNamespace(MapID=226, Region=4, District=1, Language=0),
                ),
            )

        rows: list[Any] = [account('leader@test')] + [inactive] * 63
        source = runtime.FormationRuntime(lambda: SimpleNamespace(AccountData=rows))
        with patch.object(runtime, 'get_uncached_tick_count64', lambda: 10000):
            self.assertEqual(len(source.identities()), 1)
            rows[1] = account('LEADER@test', agent=0, hwnd=301)
            self.assertEqual(source.identities(), (), 'invalid duplicate must not let the first identity win')
            rows[1] = inactive
            for stamp in (10001, 4000):
                rows[0] = account('leader@test', stamp=stamp)
                self.assertEqual(source.identities(), (), f'stale/future stamp {stamp}')

    def test_persistent_local_permission_without_actions_import(self) -> None:
        runtime = load_runtime()
        storage: dict[str, Any] = {}
        documents: list[tuple[str, str]] = []

        class Settings:
            def __init__(self, name: str, scope: str) -> None:
                documents.append((name, scope))

            def is_ready(self) -> bool:
                return True

            def get_str(self, section: str, key: str, default: str) -> str:
                return storage.get(key, default)

            def get_int(self, section: str, key: str, default: int) -> int:
                return storage.get(key, default)

            def get_bool(self, section: str, key: str, default: bool) -> bool:
                return storage.get(key, default)

            def set_str(self, section: str, key: str, value: str) -> None:
                storage[key] = value

            def set_int(self, section: str, key: str, value: int) -> None:
                storage[key] = value

            def set_bool(self, section: str, key: str, value: bool) -> None:
                storage[key] = value

        settings_module = types.ModuleType('Py4GWCoreLib.py4gwcorelib_src.Settings')
        setattr(settings_module, 'Settings', Settings)
        cache_module: Any = types.ModuleType('Py4GWCoreLib.GlobalCache')
        invalidations: list[bool] = []
        cache_module.GLOBAL_CACHE = SimpleNamespace(
            ShMem=SimpleNamespace(
                GetPartyFormation=lambda: SimpleNamespace(invalidate_consent=lambda: invalidations.append(True))
            )
        )
        with patch.dict(sys.modules, {settings_module.__name__: settings_module, cache_module.__name__: cache_module}):
            self.assertFalse(runtime.read_consent().enabled)
            runtime.save_consent(True, 'Leader@Test; SECOND@test')
            reloaded = load_runtime()
            self.assertEqual(reloaded.read_consent(), pf.Consent(True, ('leader@test', 'second@test'), 1))
            runtime.save_consent(False, 'Leader@Test')
            self.assertFalse(reloaded.read_consent().allows('leader@test'))
            self.assertEqual(set(documents), {('HeroAI/PartyFormation.ini', 'account')})
            self.assertEqual(len(invalidations), 2)

    def test_four_account_compatibility_before_join_and_manual_join_equivalence(self) -> None:
        world = World(4)
        world.runtimes[2].policy = pf.Consent()
        world.runtimes[3].policy = pf.Consent()
        world.runtimes[3].state = replace(world.runtimes[3].state, roster=(203, 999))

        def publication_live(now: int, stamp: int, ttl: int) -> bool:
            return 0 <= now - stamp < ttl

        def expired(now: int, end: int) -> bool:
            return now >= end

        def log(*args: Any, **kwargs: Any) -> None:
            pass

        namespace: dict[str, Any] = dict(
            SHMEM_MAX_PLAYERS=4,
            SHMEM_MAX_INTENTS=12,
            SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
            get_uncached_tick_count64=lambda: world.time,
            publication_is_live=publication_live,
            tick_is_expired=expired,
            WhiteboardReentryPolicy=SimpleNamespace(OWNER_REENTRANT=1),
            WhiteboardClaimStrength=SimpleNamespace(HARD=1),
            ConsoleLog=log,
            SHMEM_MODULE_NAME='test',
            PySystem=SimpleNamespace(Console=SimpleNamespace(MessageType=SimpleNamespace(Error=1))),
        )
        names = {
            '_is_visible_account',
            '_is_slot_isolated',
            '_get_message_account_snapshot',
            '_can_communicate',
            'GetHeroAIOptionsFromEmail',
            'CountLocks',
        }
        tree = ast.parse((SOURCE / 'AllAccounts.py').read_text(encoding='utf-8-sig'))
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), 'AllAccounts.py', 'exec'
            ),
            namespace,
        )

        class Gates:
            AccountData: list[Any]

            def _is_slot_active(self, index: int, now: int | None = None) -> bool:
                return True

            def _is_local_owned_slot(self, index: int) -> bool:
                return index == 0

            def _get_local_group_id(self) -> int:
                return self.AccountData[0].IsolationGroupID

            def _get_slot_group(self, index: int) -> int:
                return self.AccountData[index].IsolationGroupID

            def _find_account_slot_by_email(self, email: str) -> int:
                return next((i for i, row in enumerate(self.AccountData) if row.AccountEmail == email), -1)

            GetSlotByEmail = _find_account_slot_by_email

        for name in names:
            setattr(Gates, name, namespace[name])
        gates: Any = Gates()
        account_rows: list[Any] = []
        gates.AccountData = account_rows
        gates.HeroAIOptions = [SimpleNamespace(Combat=True) for _ in range(4)]
        for index, runtime in enumerate(world.runtimes):
            identity = runtime.state.identity
            gates.AccountData.append(
                SimpleNamespace(
                    AccountEmail=identity.email,
                    IsAccount=True,
                    IsSlotActive=True,
                    LastUpdated=world.time,
                    IsIsolated=True,
                    IsolationGroupID=(1, 2, 3, 99)[index],
                    AgentPartyData=SimpleNamespace(PartyID=10 + index),
                )
            )
        gates.Intents = [
            SimpleNamespace(
                Active=True,
                KindID=kind,
                SkillID=77,
                TargetAgentID=42,
                IsolationGroupID=group,
                ClaimStrength=1,
                ReentryPolicy=1,
                OwnerEmail=f'account{index}@test',
                ExpiresAtTick=world.time + 10000,
            )
            for index, group in enumerate((1, 2, 3, 99))
            for kind in (1, 3, 11)
        ]

        def visible_accounts() -> list[Any]:
            return [row for index, row in enumerate(gates.AccountData) if gates._is_visible_account(index)]

        def email_of(row: Any) -> str:
            return str(row.AccountEmail)

        def position_of(row: Any) -> int:
            return int(row.AgentPartyData.PartyID)

        consumers: dict[str, Any] = dict(
            GLOBAL_CACHE=SimpleNamespace(ShMem=SimpleNamespace(GetAllAccountData=visible_accounts)),
            Player=SimpleNamespace(GetAccountEmail=lambda: 'account0@test'),
            _normalize_multibox_account_email=str.casefold,
            _normalize_sync_account_email=str.casefold,
            _acc_email=email_of,
            _acc_party_position=position_of,
            _pycons_sync_account_display_name=email_of,
        )
        for relative, name in (
            ('Widgets/Guild Wars/Items & Loot/MerchantRules.py', '_get_multibox_accounts'),
            ('Widgets/Automation/Helpers/Pycons.py', '_get_pycons_sync_accounts'),
        ):
            consumer_tree = ast.parse((ROOT / relative).read_text(encoding='utf-8-sig'))
            consumer = next(
                node for node in ast.walk(consumer_tree) if isinstance(node, ast.FunctionDef) and node.name == name
            )
            consumer.decorator_list = []
            exec(compile(ast.Module(body=[consumer], type_ignores=[]), relative, 'exec'), consumers)
        merchant = SimpleNamespace(_get_account_party_position=position_of, _get_account_display_name=email_of)

        def observe() -> tuple[tuple[Any, ...], ...]:
            return (
                tuple(gates._is_visible_account(i) for i in range(4)),
                tuple(gates._can_communicate('account0@test', row.AccountEmail) for row in gates.AccountData),
                tuple(gates.GetHeroAIOptionsFromEmail(row.AccountEmail) is not None for row in gates.AccountData),
                tuple(row.IsolationGroupID for row in gates.AccountData),
                tuple(
                    gates.CountLocks(kind, 77, 42, group, '', world.time)
                    for group in (1, 2, 3, 99)
                    for kind in (1, 3, 11)
                ),
                tuple(email_of(row) for row in consumers['_get_multibox_accounts'](merchant)),
                tuple(email_of(row) for row in consumers['_get_pycons_sync_accounts']()),
            )

        before = observe()
        self.assertEqual(before[0], (True, False, False, False))
        self.assertEqual(before[5:], ((), ()))
        world.primary()
        self.assertEqual(observe(), before, 'receiver authorization must not change ordinary authority or reservations')
        world.drain(1)
        self.assertEqual(observe(), before, 'invitation dispatch must not merge isolation groups')
        manual = copy.deepcopy(gates)
        # Execute the unchanged production resolver on equivalent native party
        # publications after manual joining and after protocol-confirmed joining.
        isolation_tree = ast.parse(
            (ROOT / 'Py4GWCoreLib/botting_tree_src/isolation.py').read_text(encoding='utf-8-sig')
        )
        resolver = next(
            node
            for node in isolation_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == 'resolve_isolation_group_id'
        )
        for registry in (manual, gates):
            registry.AccountData[1].AgentPartyData.PartyID = registry.AccountData[0].AgentPartyData.PartyID

            def get_account(email: str) -> Any:
                return next(row for row in registry.AccountData if row.AccountEmail == email)

            def get_members(email: str) -> Any:
                party = get_account(email).AgentPartyData.PartyID
                return party, tuple(row for row in registry.AccountData if row.AgentPartyData.PartyID == party)

            def no_assignment(email: str) -> None:
                return None

            def eligible(member: Any, policies: Any) -> bool:
                return True

            isolation_namespace: dict[str, Any] = dict(
                _normalized_email=str.casefold,
                _get_account_data=get_account,
                _get_persisted_group_assignment=no_assignment,
                _get_party_members=get_members,
                read_account_isolation_policies=dict,
                _is_account_isolation_eligible=eligible,
            )
            exec(compile(ast.Module(body=[resolver], type_ignores=[]), 'isolation.py', 'exec'), isolation_namespace)
            resolved = isolation_namespace['resolve_isolation_group_id']('account0@test')
            registry.AccountData[0].IsolationGroupID = resolved
            registry.AccountData[1].IsolationGroupID = resolved
        world.joined()
        world.advance()
        world.advance()
        self.assertEqual(vars(gates), vars(manual))
        self.assertEqual(observe()[0], (True, True, False, False))
        self.assertEqual(observe()[5:], (('account1@test',), ('account1@test',)))
        self.assertEqual(world.sends, [(0, 201), (1, 200)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
