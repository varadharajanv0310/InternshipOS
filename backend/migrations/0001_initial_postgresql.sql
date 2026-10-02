-- Core schema 0001; generated from SQLAlchemy models; PostgreSQL.

BEGIN;


CREATE TABLE activity (
	kind VARCHAR(100) NOT NULL, 
	title VARCHAR(1000) NOT NULL, 
	body TEXT NOT NULL, 
	entity_type VARCHAR(100), 
	entity_id VARCHAR(36), 
	data JSON NOT NULL, 
	before JSON, 
	after JSON, 
	undone_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_activity_entity_id ON activity (entity_id);

CREATE INDEX ix_activity_kind ON activity (kind);


CREATE TABLE ai_usage (
	action VARCHAR(100) NOT NULL, 
	provider VARCHAR(80) NOT NULL, 
	model VARCHAR(200) NOT NULL, 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	cost_usd FLOAT NOT NULL, 
	reserved_usd FLOAT NOT NULL, 
	status VARCHAR(80) NOT NULL, 
	request_hash VARCHAR(64), 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ai_nonnegative CHECK (cost_usd >= 0 AND reserved_usd >= 0)
)

;

CREATE INDEX ix_ai_usage_request_hash ON ai_usage (request_hash);


CREATE TABLE companies (
	name VARCHAR(300) NOT NULL, 
	domain VARCHAR(300), 
	careers_url TEXT, 
	logo_url TEXT, 
	verified BOOLEAN NOT NULL, 
	description TEXT NOT NULL, 
	industry VARCHAR(200), 
	locations JSON NOT NULL, 
	aliases JSON NOT NULL, 
	metadata_json JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_companies_domain ON companies (domain);

CREATE INDEX ix_companies_name ON companies (name);


CREATE TABLE email_messages (
	provider_message_id VARCHAR(300) NOT NULL, 
	thread_id VARCHAR(300), 
	sender TEXT NOT NULL, 
	subject TEXT NOT NULL, 
	body TEXT NOT NULL, 
	data JSON NOT NULL, 
	status VARCHAR(80) NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (provider_message_id)
)

;

CREATE INDEX ix_email_messages_thread_id ON email_messages (thread_id);


CREATE TABLE integrations (
	provider VARCHAR(80) NOT NULL, 
	status VARCHAR(80) NOT NULL, 
	data JSON NOT NULL, 
	credentials_encrypted TEXT, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (provider)
)

;


CREATE TABLE notifications (
	title VARCHAR(1000) NOT NULL, 
	body TEXT NOT NULL, 
	kind VARCHAR(80) NOT NULL, 
	read BOOLEAN NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE profile_versions (
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE projects (
	name VARCHAR(500) NOT NULL, 
	github_url TEXT, 
	technologies JSON NOT NULL, 
	description TEXT NOT NULL, 
	approved BOOLEAN NOT NULL, 
	approved_bullets JSON NOT NULL, 
	role_tags JSON NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (github_url)
)

;


CREATE TABLE resumes (
	name VARCHAR(300) NOT NULL, 
	role_focus VARCHAR(100) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE settings (
	key VARCHAR(100) NOT NULL, 
	value JSON, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
)

;


CREATE TABLE company_sources (
	company_id VARCHAR(36) NOT NULL, 
	provider VARCHAR(80) NOT NULL, 
	url TEXT NOT NULL, 
	tenant VARCHAR(300), 
	board VARCHAR(300), 
	priority INTEGER NOT NULL, 
	cadence_hours FLOAT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	verified BOOLEAN NOT NULL, 
	config JSON NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	last_checked TIMESTAMP WITH TIME ZONE, 
	last_success TIMESTAMP WITH TIME ZONE, 
	last_error TEXT, 
	consecutive_failures INTEGER NOT NULL, 
	job_count INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_company_provider_url UNIQUE (company_id, provider, url), 
	FOREIGN KEY(company_id) REFERENCES companies (id)
)

;

CREATE INDEX ix_company_sources_company_id ON company_sources (company_id);

CREATE INDEX ix_company_sources_provider ON company_sources (provider);


CREATE TABLE opportunities (
	company_id VARCHAR(36) NOT NULL, 
	title VARCHAR(800) NOT NULL, 
	description TEXT NOT NULL, 
	description_html TEXT NOT NULL, 
	role_family VARCHAR(80) NOT NULL, 
	opportunity_type VARCHAR(80) NOT NULL, 
	location VARCHAR(800) NOT NULL, 
	country VARCHAR(120), 
	work_mode VARCHAR(60) NOT NULL, 
	compensation JSON NOT NULL, 
	skills JSON NOT NULL, 
	requirements JSON NOT NULL, 
	responsibilities JSON NOT NULL, 
	posted_at TIMESTAMP WITH TIME ZONE, 
	deadline TIMESTAMP WITH TIME ZONE, 
	first_seen TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_verified TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(40) NOT NULL, 
	saved BOOLEAN NOT NULL, 
	notes TEXT NOT NULL, 
	canonical_url TEXT, 
	apply_url TEXT, 
	requisition_id VARCHAR(300), 
	fit_score FLOAT, 
	fit_confidence VARCHAR(40) NOT NULL, 
	worth_score FLOAT, 
	eligibility VARCHAR(60) NOT NULL, 
	trust_state VARCHAR(60) NOT NULL, 
	risk_reasons JSON NOT NULL, 
	summary TEXT NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_fit_range CHECK (fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)), 
	CONSTRAINT ck_worth_range CHECK (worth_score IS NULL OR (worth_score >= 0 AND worth_score <= 100)), 
	FOREIGN KEY(company_id) REFERENCES companies (id)
)

;

CREATE INDEX ix_opportunities_company_id ON opportunities (company_id);

CREATE INDEX ix_opportunities_first_seen ON opportunities (first_seen);

CREATE INDEX ix_opportunities_opportunity_type ON opportunities (opportunity_type);

CREATE INDEX ix_opportunities_requisition_id ON opportunities (requisition_id);

CREATE INDEX ix_opportunities_role_family ON opportunities (role_family);

CREATE INDEX ix_opportunities_saved ON opportunities (saved);

CREATE INDEX ix_opportunities_status ON opportunities (status);

CREATE INDEX ix_opportunity_company_requisition ON opportunities (company_id, requisition_id);


CREATE TABLE resume_versions (
	resume_id VARCHAR(36) NOT NULL, 
	data JSON NOT NULL, 
	artifact_path TEXT, 
	artifact_hash VARCHAR(64), 
	status VARCHAR(60) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(resume_id) REFERENCES resumes (id)
)

;

CREATE INDEX ix_resume_versions_resume_id ON resume_versions (resume_id);


CREATE TABLE applications (
	opportunity_id VARCHAR(36) NOT NULL, 
	attempt INTEGER NOT NULL, 
	stage VARCHAR(40) NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	resume_version_id VARCHAR(36), 
	notes TEXT NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_application_attempt UNIQUE (opportunity_id, attempt), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id), 
	FOREIGN KEY(resume_version_id) REFERENCES resume_versions (id)
)

;

CREATE INDEX ix_applications_opportunity_id ON applications (opportunity_id);

CREATE INDEX ix_applications_stage ON applications (stage);


CREATE TABLE evaluations (
	opportunity_id VARCHAR(36) NOT NULL, 
	profile_version_id VARCHAR(36), 
	input_hash VARCHAR(64) NOT NULL, 
	version VARCHAR(80) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id), 
	FOREIGN KEY(profile_version_id) REFERENCES profile_versions (id)
)

;

CREATE INDEX ix_evaluations_input_hash ON evaluations (input_hash);

CREATE INDEX ix_evaluations_opportunity_id ON evaluations (opportunity_id);


CREATE TABLE fetch_runs (
	company_source_id VARCHAR(36) NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(40) NOT NULL, 
	complete BOOLEAN NOT NULL, 
	coverage_scope VARCHAR(300) NOT NULL, 
	observed_count INTEGER NOT NULL, 
	error TEXT, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_source_id) REFERENCES company_sources (id)
)

;

CREATE INDEX ix_fetch_runs_company_source_id ON fetch_runs (company_source_id);


CREATE TABLE job_sources (
	company_source_id VARCHAR(36) NOT NULL, 
	opportunity_id VARCHAR(36) NOT NULL, 
	external_id VARCHAR(700) NOT NULL, 
	requisition_id VARCHAR(300), 
	url TEXT, 
	first_seen TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_seen TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_detail_checked TIMESTAMP WITH TIME ZONE, 
	latest_hash VARCHAR(64), 
	missed_complete_runs INTEGER NOT NULL, 
	first_missing_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(40) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_scoped_external_job UNIQUE (company_source_id, external_id), 
	FOREIGN KEY(company_source_id) REFERENCES company_sources (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id)
)

;

CREATE INDEX ix_job_sources_company_source_id ON job_sources (company_source_id);

CREATE INDEX ix_job_sources_opportunity_id ON job_sources (opportunity_id);


CREATE TABLE application_events (
	application_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	from_stage VARCHAR(40), 
	to_stage VARCHAR(40), 
	source VARCHAR(80) NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	dedupe_key VARCHAR(300), 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_application_event_key UNIQUE (application_id, dedupe_key), 
	FOREIGN KEY(application_id) REFERENCES applications (id)
)

;

CREATE INDEX ix_application_events_application_id ON application_events (application_id);


CREATE TABLE email_links (
	email_message_id VARCHAR(36) NOT NULL, 
	application_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_email_application_event UNIQUE (email_message_id, application_id, event_type), 
	FOREIGN KEY(email_message_id) REFERENCES email_messages (id), 
	FOREIGN KEY(application_id) REFERENCES applications (id)
)

;

CREATE INDEX ix_email_links_application_id ON email_links (application_id);

CREATE INDEX ix_email_links_email_message_id ON email_links (email_message_id);


CREATE TABLE identity_decisions (
	opportunity_id VARCHAR(36) NOT NULL, 
	candidate_id VARCHAR(36), 
	job_source_id VARCHAR(36), 
	decision VARCHAR(40) NOT NULL, 
	evidence JSON NOT NULL, 
	reversed_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id), 
	FOREIGN KEY(candidate_id) REFERENCES opportunities (id), 
	FOREIGN KEY(job_source_id) REFERENCES job_sources (id)
)

;

CREATE INDEX ix_identity_decisions_candidate_id ON identity_decisions (candidate_id);

CREATE INDEX ix_identity_decisions_opportunity_id ON identity_decisions (opportunity_id);


CREATE TABLE snapshots (
	job_source_id VARCHAR(36) NOT NULL, 
	fetch_run_id VARCHAR(36) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	raw JSON NOT NULL, 
	normalized JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_source_id) REFERENCES job_sources (id), 
	FOREIGN KEY(fetch_run_id) REFERENCES fetch_runs (id)
)

;

CREATE INDEX ix_snapshots_content_hash ON snapshots (content_hash);

CREATE INDEX ix_snapshots_fetch_run_id ON snapshots (fetch_run_id);

CREATE INDEX ix_snapshots_job_source_id ON snapshots (job_source_id);


CREATE TABLE tasks (
	title VARCHAR(1000) NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE, 
	completed BOOLEAN NOT NULL, 
	application_id VARCHAR(36), 
	opportunity_id VARCHAR(36), 
	kind VARCHAR(60) NOT NULL, 
	notes TEXT NOT NULL, 
	date_precision VARCHAR(40) NOT NULL, 
	dedupe_key VARCHAR(300), 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(application_id) REFERENCES applications (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id), 
	UNIQUE (dedupe_key)
)

;

CREATE INDEX ix_tasks_application_id ON tasks (application_id);

CREATE INDEX ix_tasks_due_at ON tasks (due_at);

CREATE INDEX ix_tasks_opportunity_id ON tasks (opportunity_id);


CREATE TABLE calendar_links (
	task_id VARCHAR(36) NOT NULL, 
	external_id VARCHAR(400), 
	etag VARCHAR(500), 
	data JSON NOT NULL, 
	status VARCHAR(80) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id), 
	UNIQUE (external_id)
)

;


CREATE TABLE evidence (
	opportunity_id VARCHAR(36) NOT NULL, 
	snapshot_id VARCHAR(36), 
	field VARCHAR(200) NOT NULL, 
	value JSON, 
	source_url TEXT, 
	method VARCHAR(80) NOT NULL, 
	confidence VARCHAR(40) NOT NULL, 
	data JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id), 
	FOREIGN KEY(snapshot_id) REFERENCES snapshots (id)
)

;

CREATE INDEX ix_evidence_opportunity_id ON evidence (opportunity_id);

CREATE INDEX ix_evidence_snapshot_id ON evidence (snapshot_id);

COMMIT;
