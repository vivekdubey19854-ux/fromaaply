"""Harden website registry metadata and seed official Indian portals."""
import json
import sqlalchemy as sa
from alembic import op

revision = "0014_registry_production"
down_revision = "0013_ai_usage_ledger"
branch_labels = None
depends_on = None

OFFICIAL = [
    ("Staff Selection Commission", "government_exam", "https://ssc.gov.in", ["ssc.gov.in"], ["login", "registration", "application"], ["otp", "captcha", "legal_declaration", "final_review"]),
    ("Union Public Service Commission", "government_exam", "https://upsc.gov.in", ["upsc.gov.in"], ["examinations", "online-application"], ["otp", "captcha", "legal_declaration", "final_review"]),
    ("National Scholarship Portal", "scholarship", "https://scholarships.gov.in", ["scholarships.gov.in"], ["student", "application"], ["otp", "captcha", "legal_declaration", "final_review"]),
    ("National Testing Agency", "government_exam", "https://exams.nta.ac.in", ["exams.nta.ac.in"], ["online-application", "registration"], ["otp", "captcha", "payment", "legal_declaration", "final_review"]),
]


def upgrade() -> None:
    with op.batch_alter_table("website_registry") as batch:
        batch.add_column(sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("version", sa.String(40), nullable=False, server_default="1.0.0"))
        batch.add_column(sa.Column("health_status", sa.String(30), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("last_health_check", sa.DateTime()))
        batch.add_column(sa.Column("verified_at", sa.DateTime()))
        batch.add_column(sa.Column("allowed_paths_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("supported_fields_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("mapping_metadata_json", sa.Text(), nullable=False, server_default="{}"))
        batch.create_index("ix_website_registry_verified", ["verified"])
        batch.create_index("ix_website_registry_health_status", ["health_status"])
    bind = op.get_bind()
    for name, category, base_url, domains, paths, gates in OFFICIAL:
        bind.execute(sa.text("""
            INSERT INTO website_registry
            (website_id, name, category, base_url, allowed_domains_json, enabled, config_json,
             verified, version, health_status, allowed_paths_json, supported_fields_json, mapping_metadata_json, verified_at)
            VALUES (:id, :name, :category, :base_url, :domains, false, :config, true, '1.0.0', 'unknown', :paths, :fields, :mapping, CURRENT_TIMESTAMP)
            ON CONFLICT (website_id) DO NOTHING
        """), {"id": f"official-{name.lower().replace(' ', '-')[:24]}", "name": name, "category": category, "base_url": base_url, "domains": json.dumps(domains), "config": json.dumps({"human_gates": gates, "official_source": base_url}), "paths": json.dumps(paths), "fields": json.dumps(["full_name", "date_of_birth", "gender", "email", "phone", "address", "education", "documents"]), "mapping": json.dumps({"version": "1.0.0", "confidence_threshold": 0.92})})


def downgrade() -> None:
    with op.batch_alter_table("website_registry") as batch:
        batch.drop_index("ix_website_registry_health_status")
        batch.drop_index("ix_website_registry_verified")
        for name in ("mapping_metadata_json", "supported_fields_json", "allowed_paths_json", "verified_at", "last_health_check", "health_status", "version", "verified"):
            batch.drop_column(name)
