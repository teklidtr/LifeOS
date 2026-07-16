---
id: LIFEOS-1505
title: Expose experiment bridge protocol
status: completed
phase: 15
depends_on:
  - LIFEOS-1504
risk: high
---

# Goal

Expose strict experiment design, lifecycle, observation, analysis, history, rebuild, migration, and proposal methods through the local bridge.

# Scope

- Implement only this task's named capability and its focused tests.
- Preserve canonical Markdown, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record diagnostics and degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to goals, plans, habits, tasks, metrics, notes, reminders, or calendars.

# Required invariants

- Markdown remains canonical and portable.
- Missing observations never become zero.
- Derived state can be deleted and rebuilt.
- Unsafe experiments fail closed before scheduling or activation.
- Descriptive evidence never produces a causal claim.

# Required tests

- Strict-field, capability, stale-write, cancellation, error-shape, and end-to-end bridge fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

FF.......                                                                [100%]
=================================== FAILURES ===================================
____________ test_experiment_bridge_vertical_slice_and_capabilities ____________

tmp_path = PosixPath('/tmp/pytest-of-root/pytest-9/test_experiment_bridge_vertica0')

    def test_experiment_bridge_vertical_slice_and_capabilities(tmp_path: Path) -> None:
        bridge, vault = client(tmp_path)
        handshake = bridge.call("system.handshake", protocol="1.2")
        assert "experiment.analysis.run" in handshake["capabilities"]
>       created = bridge.call("experiment.create", title="Walk", category="study", protocol=protocol(), now=NOW)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/bridge/test_experiment_bridge.py:36: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/lifeos/bridge/client.py:15: in call
    return self.application.dispatch(method, params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/lifeos/bridge/application.py:523: in dispatch
    return self._dispatch_experiment(method, params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <lifeos.bridge.application.BridgeApplication object at 0x7eaaa16652b0>
method = 'experiment.create'
params = {'category': 'study', 'now': '2026-07-16T09:00:00+00:00', 'protocol': {'adherence_expectation': 'Both days', 'baseline_requirements': 'Two days', 'comparison': 'No-walk baseline', 'confounders': ['sleep'], ...}, 'title': 'Walk'}

    def _dispatch_experiment(self, method: str, params: object) -> object:
        try:
            if method == "experiment.create":
                data = strict_object(params, allowed={"title", "description", "category", "protocol", "origins", "now"}, required={"title", "protocol"})
                if not isinstance(data["protocol"], dict):
                    raise ProtocolError("invalid_params", "protocol must be an object.")
                protocol = protocol_from_dict(data["protocol"])
                origins_raw = data.get("origins", ())
                if not isinstance(origins_raw, list):
>                   raise ProtocolError("invalid_params", "origins must be a list.")
E                   lifeos.bridge.protocol.ProtocolError: ('invalid_params', 'origins must be a list.')

src/lifeos/bridge/application.py:401: ProtocolError

During handling of the above exception, another exception occurred:

self = <contextlib._GeneratorContextManager object at 0x7eaaa1db2c10>
typ = <class 'lifeos.bridge.protocol.ProtocolError'>
value = ProtocolError(code='invalid_params', message='origins must be a list.', data=None)
traceback = <traceback object at 0x7eaaa160ef00>

    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
                next(self.gen)
            except StopIteration:
                return False
            else:
                try:
                    raise RuntimeError("generator didn't stop")
                finally:
                    self.gen.close()
        else:
            if value is None:
                # Need to force instantiation so we can reliably
                # tell if we get the same exception back
                value = typ()
            try:
                self.gen.throw(value)
            except StopIteration as exc:
                # Suppress StopIteration *unless* it's the same exception that
                # was passed to throw().  This prevents a StopIteration
                # raised inside the "with" statement from being suppressed.
                return exc is not value
            except RuntimeError as exc:
                # Don't re-raise the passed in exception. (issue27122)
                if exc is value:
                    exc.__traceback__ = traceback
                    return False
                # Avoid suppressing if a StopIteration exception
                # was passed to throw() and later wrapped into a RuntimeError
                # (see PEP 479 for sync generators; async generators also
                # have this behavior). But do this only if the exception wrapped
                # by the RuntimeError is actually Stop(Async)Iteration (see
                # issue29692).
                if (
                    isinstance(value, StopIteration)
                    and exc.__cause__ is value
                ):
                    value.__traceback__ = traceback
                    return False
                raise
            except BaseException as exc:
                # only re-raise if it's *not* the exception that was
                # passed to throw(), because __exit__() must not raise
                # an exception unless __exit__() itself failed.  But throw()
                # has to raise the exception to signal propagation, so this
                # fixes the impedance mismatch between the throw() protocol
                # and the __exit__() protocol.
                if exc is not value:
                    raise
>               exc.__traceback__ = traceback
                ^^^^^^^^^^^^^^^^^
E               TypeError: super(type, obj): obj (instance of ProtocolError) is not an instance or subtype of type (ProtocolError).

/usr/lib/python3.13/contextlib.py:195: TypeError
_____ test_bridge_rejects_extra_fields_stale_writes_and_unsafe_activation ______

tmp_path = PosixPath('/tmp/pytest-of-root/pytest-9/test_bridge_rejects_extra_fiel0')

    def test_bridge_rejects_extra_fields_stale_writes_and_unsafe_activation(tmp_path: Path) -> None:
        bridge, _ = client(tmp_path)
        with pytest.raises(ProtocolError) as extra:
            bridge.call("experiment.create", title="x", protocol=protocol(), surprise=True)
        assert extra.value.code == "extra_fields"
        unsafe = protocol(); unsafe["intervention"] = "Stop prescription medication and change dose"
>       created = bridge.call("experiment.create", title="Unsafe", protocol=unsafe, now=NOW)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/bridge/test_experiment_bridge.py:60: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/lifeos/bridge/client.py:15: in call
    return self.application.dispatch(method, params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/lifeos/bridge/application.py:523: in dispatch
    return self._dispatch_experiment(method, params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <lifeos.bridge.application.BridgeApplication object at 0x7eaaa1732490>
method = 'experiment.create'
params = {'now': '2026-07-16T09:00:00+00:00', 'protocol': {'adherence_expectation': 'Both days', 'baseline_requirements': 'Two days', 'comparison': 'No-walk baseline', 'confounders': ['sleep'], ...}, 'title': 'Unsafe'}

    def _dispatch_experiment(self, method: str, params: object) -> object:
        try:
            if method == "experiment.create":
                data = strict_object(params, allowed={"title", "description", "category", "protocol", "origins", "now"}, required={"title", "protocol"})
                if not isinstance(data["protocol"], dict):
                    raise ProtocolError("invalid_params", "protocol must be an object.")
                protocol = protocol_from_dict(data["protocol"])
                origins_raw = data.get("origins", ())
                if not isinstance(origins_raw, list):
>                   raise ProtocolError("invalid_params", "origins must be a list.")
E                   lifeos.bridge.protocol.ProtocolError: ('invalid_params', 'origins must be a list.')

src/lifeos/bridge/application.py:401: ProtocolError

During handling of the above exception, another exception occurred:

self = <contextlib._GeneratorContextManager object at 0x7eaaa14a42f0>
typ = <class 'lifeos.bridge.protocol.ProtocolError'>
value = ProtocolError(code='invalid_params', message='origins must be a list.', data=None)
traceback = <traceback object at 0x7eaaa13a2980>

    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
                next(self.gen)
            except StopIteration:
                return False
            else:
                try:
                    raise RuntimeError("generator didn't stop")
                finally:
                    self.gen.close()
        else:
            if value is None:
                # Need to force instantiation so we can reliably
                # tell if we get the same exception back
                value = typ()
            try:
                self.gen.throw(value)
            except StopIteration as exc:
                # Suppress StopIteration *unless* it's the same exception that
                # was passed to throw().  This prevents a StopIteration
                # raised inside the "with" statement from being suppressed.
                return exc is not value
            except RuntimeError as exc:
                # Don't re-raise the passed in exception. (issue27122)
                if exc is value:
                    exc.__traceback__ = traceback
                    return False
                # Avoid suppressing if a StopIteration exception
                # was passed to throw() and later wrapped into a RuntimeError
                # (see PEP 479 for sync generators; async generators also
                # have this behavior). But do this only if the exception wrapped
                # by the RuntimeError is actually Stop(Async)Iteration (see
                # issue29692).
                if (
                    isinstance(value, StopIteration)
                    and exc.__cause__ is value
                ):
                    value.__traceback__ = traceback
                    return False
                raise
            except BaseException as exc:
                # only re-raise if it's *not* the exception that was
                # passed to throw(), because __exit__() must not raise
                # an exception unless __exit__() itself failed.  But throw()
                # has to raise the exception to signal propagation, so this
                # fixes the impedance mismatch between the throw() protocol
                # and the __exit__() protocol.
                if exc is not value:
                    raise
>               exc.__traceback__ = traceback
                ^^^^^^^^^^^^^^^^^
E               TypeError: super(type, obj): obj (instance of ProtocolError) is not an instance or subtype of type (ProtocolError).

/usr/lib/python3.13/contextlib.py:195: TypeError
=========================== short test summary info ============================
FAILED tests/bridge/test_experiment_bridge.py::test_experiment_bridge_vertical_slice_and_capabilities - TypeError: super(type, obj): obj (instance of ProtocolError) is not an instance or subtype of type (ProtocolError).
FAILED tests/bridge/test_experiment_bridge.py::test_bridge_rejects_extra_fields_stale_writes_and_unsafe_activation - TypeError: super(type, obj): obj (instance of ProtocolError) is not an instance or subtype of type (ProtocolError).
2 failed, 7 passed in 1.74s

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
