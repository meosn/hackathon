from app.briefing.agent_setup import configuration
from app.briefing.realtime import session_config
from app.briefing.voice_policy import LISTENING_POLICY


def test_native_agent_waits_silently_and_can_skip_inactivity_without_checkins():
    config = configuration()['conversation_config']
    assert config['realtime_model'] == 'eleven_realtime_v1_max'
    assert config['agent']['first_message'] == ''
    assert config['turn']['turn_timeout'] == 30
    assert config['turn']['soft_timeout_config']['timeout_seconds'] == -1
    assert config['agent']['prompt']['prompt'].startswith(LISTENING_POLICY)
    skip = config['agent']['prompt']['built_in_tools']['skip_turn']
    assert skip['params'] == {'system_tool_type':'skip_turn', 'wait_timeout_secs':-1}
    for preset in config['language_presets'].values():
        assert preset['overrides']['agent']['first_message'] == ''


def test_openai_voice_does_not_treat_silence_as_a_question():
    instructions = session_config('en',[])['instructions']
    assert 'An open microphone is not a request' in instructions
    assert 'ask once to repeat the question' in instructions


def test_live_patch_keeps_existing_tools_native_model_and_other_turn_settings():
    from app.briefing.agent_setup import listening_policy_patch
    before = {'conversation_config': {'realtime_model':'eleven_realtime_v1_max','turn':{'spelling_patience':'auto','turn_timeout':7},'agent':{'prompt':{'prompt':'Existing news and research instructions.','tool_ids':['news','research'],'built_in_tools':{'language_detection':{'type':'system'}}}}}}
    patch = listening_policy_patch(before)['conversation_config']
    assert patch['realtime_model']=='eleven_realtime_v1_max'
    assert patch['agent']['prompt']['tool_ids']==['news','research']
    assert patch['agent']['prompt']['prompt'].endswith('Existing news and research instructions.')
    assert patch['agent']['prompt']['built_in_tools']['language_detection']=={'type':'system'}
    assert patch['turn']['spelling_patience']=='auto'
    assert 'tts' not in patch
    assert listening_policy_patch({'conversation_config':patch})['conversation_config']['agent']['prompt']['prompt'].count('LISTENING POLICY:')==1
