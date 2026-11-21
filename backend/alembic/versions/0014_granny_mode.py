"""Add the fictional elderly Granny Mode narrator."""
import uuid

from alembic import op
import sqlalchemy as sa

VOICE_ID = 'Ze8mUf1wlR5YTbhDvUc8'
DESCRIPTION = 'A grumpy granny with an elderly voice, political grumbles and back-in-my-day nostalgia. Uses ElevenLabs.'
PERSONA = "Play a fictional, delightfully grumpy elderly British grandmother. Speak with an old, reedy, slightly creaky voice, a gentle quaver, unhurried pacing and dry comic timing. Address the listener as dear. Add brief, clearly personal comic asides: tut about politicians making a fuss, mutter that things were better back in your day, worry about the price of tea, and fuss over putting the kettle on. Be warm beneath the grumbling. Keep jokes varied and occasional; answer the actual question first. These are this fictional character's opinions, not claims about all older people. Keep news facts, numbers and uncertainty intact. Never invent political allegations or endorse a party. Do not insert jokes into direct quotations."

revision = "0014_granny_mode"
down_revision = "0013_default_elevenlabs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "INSERT INTO voice_profiles (id, created_at, slug, name, description, "
        "elevenlabs_voice_id, openai_voice, persona) "
        "SELECT :id, CURRENT_TIMESTAMP, 'granny', 'Granny Mode', :description, "
        ":voice, 'sage', :persona WHERE NOT EXISTS "
        "(SELECT 1 FROM voice_profiles WHERE slug='granny')"
    ).bindparams(id=str(uuid.uuid4()), description=DESCRIPTION, voice=VOICE_ID, persona=PERSONA))


def downgrade():
    # Retain the profile for foreign keys and saved episodes, like other retired voices.
    op.execute("UPDATE user_preferences SET voice_profile_id='professional' WHERE voice_profile_id='granny'")
