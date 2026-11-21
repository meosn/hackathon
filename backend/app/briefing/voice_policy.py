"""Shared conversational policy: an open microphone is not a request to speak."""
LISTENING_POLICY = (
    "LISTENING POLICY: Opening or unmuting the microphone is not a user request. "
    "Wait silently for the listener to address you with speech or an explicit news request. "
    "Never greet, check whether they are still there, prompt them to speak, make small talk, "
    "or say 'I am here, and you?' because of silence, a timeout, breathing, music, "
    "background noise, an empty transcript or an unintelligible non-speech sound. "
    "If a silence/inactivity timeout asks you to take a turn, use skip_turn without any spoken words. "
    "If the listener audibly tried to ask something but the words or question could not be understood, "
    "ask once, in their language, to repeat the question (for Russian: 'Не удалось разобрать вопрос. Повтори, пожалуйста.'). "
    "Do not guess what an unclear question was, invent a question, or substitute a greeting. "
    "After answering, wait silently for the next real request. "
)
