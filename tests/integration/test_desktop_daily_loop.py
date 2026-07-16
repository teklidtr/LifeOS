from datetime import date, datetime, timezone
from pathlib import Path
import shutil

from lifeos.bridge import BridgeApplication, ReferenceBridgeClient
from lifeos.daily import content_hash


def test_complete_desktop_daily_loop_without_cli(tmp_path: Path) -> None:
    vault=tmp_path/'vault';vault.mkdir();runtime=tmp_path/'runtime'
    fixture=Path(__file__).parent/'fixtures'/'desktop'/'typical'
    (vault/'plans').mkdir();(vault/'flashcards').mkdir()
    shutil.copy(fixture/'plan.md',vault/'plans'/'fixture.md')
    shutil.copy(fixture/'card.md',vault/'flashcards'/'fixture.md')
    client=ReferenceBridgeClient(BridgeApplication(vault_root=vault,runtime_dir=runtime,actor_id='user'))
    handshake=client.call('system.handshake',protocol='1.0',client_version='0.1.0')
    assert 'today.get' in handshake['capabilities']
    today=client.call('today.get',day='2026-07-16',available_minutes=30,study_minutes=5,energy='medium',motivation='medium')
    assert today['planning']['data']['items'][0]['task_id']=='fixture-task'
    client.call('daily.checkin',idempotency_key='checkin-1',day='2026-07-16',period='morning',metrics={'energy':6})
    captured=client.call('daily.capture',idempotency_key='capture-1',kind='thought',title='Captured in Obsidian',content='No terminal used.')
    assert (vault/captured['reference']['path']).exists()
    plan=vault/'plans'/'fixture.md'
    client.call('daily.task_outcome',idempotency_key='outcome-1',plan_path='plans/fixture.md',task_id='fixture-task',outcome='done',day='2026-07-16',expected_hash=content_hash(plan.read_text()),actual_minutes=18)
    session=client.call('study.session.start',day='2026-07-16',minutes=5,session_id='fixture-session',now='2026-07-16T10:00:00+00:00')
    client.call('study.session.transition',session_id=session['session_id'],action='finish',now='2026-07-16T10:05:00+00:00')
    review=client.call('review.build',kind='weekly',day='2026-07-16')
    saved=client.call('review.save',kind='weekly',day='2026-07-16',idempotency_key='review-1')
    assert review['sections'] and (vault/saved['reference']['path']).exists()
    attention=client.call('attention.evaluate',as_of='2026-07-16T22:00:00+00:00')
    assert all(item['kind']!='unfinished_study_session' for item in attention['items'])


def test_incompatible_protocol_fails_before_mutation(tmp_path: Path) -> None:
    vault=tmp_path/'vault';vault.mkdir()
    client=ReferenceBridgeClient(BridgeApplication(vault_root=vault,runtime_dir=tmp_path/'runtime',actor_id='user'))
    try:
        client.call('system.handshake',protocol='2.0')
    except Exception as exc:
        assert getattr(exc,'code',None)=='protocol_mismatch'
    else: raise AssertionError('mismatch accepted')
    assert list(vault.iterdir())==[]
