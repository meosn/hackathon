"""Replace the energetic preset with the owner's supplied character voice."""
from alembic import op
import sqlalchemy as sa

revision = "0007_trump_voice"
down_revision = "0006_schedule_weekdays"
branch_labels = None
depends_on = None

VOICE_ID = "CBtIsr4irOknVyIz3EzI"
PERSONA = "Use the supplied AI character voice with emphatic, conversational delivery and deliberate pauses. You are an AI news narrator, not the real Donald Trump. Preserve verified news facts and do not add political opinions or endorsements."


def upgrade():
    op.execute(sa.text(
        "UPDATE voice_profiles SET name=:name, description=:description, "
        "elevenlabs_voice_id=:voice, persona=:persona WHERE slug='energetic'"
    ).bindparams(name="Donald Trump", description="AI character voice from the supplied recording. Uses ElevenLabs.", voice=VOICE_ID, persona=PERSONA))


def downgrade():
    op.execute(sa.text(
        "UPDATE voice_profiles SET name='Energetic Speaker', description='A brisk, animated delivery.', "
        "elevenlabs_voice_id='TX3LPaxmHKxFdv7VOQHJ', "
        "persona='Speak like an energetic speaker: lively, upbeat and engaging, without shouting.' "
        "WHERE slug='energetic' AND elevenlabs_voice_id=:voice"
    ).bindparams(voice=VOICE_ID))
