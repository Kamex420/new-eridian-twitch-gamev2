BEGIN TRANSACTION;
CREATE TABLE account_links_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	twitch_uid VARCHAR(96) NOT NULL, 
	discord_uid VARCHAR(96) NOT NULL, 
	linked_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_link_twitch_v52 UNIQUE (channel_id, twitch_uid), 
	CONSTRAINT uq_link_discord_v52 UNIQUE (channel_id, discord_uid)
);
CREATE TABLE account_name_history_v541 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	provider_uid VARCHAR(96) NOT NULL, 
	display_name VARCHAR(80) NOT NULL, 
	first_seen DATETIME NOT NULL, 
	last_seen DATETIME NOT NULL, 
	seen_count INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_name_history_v541 UNIQUE (channel_id, provider, provider_uid, display_name)
);
CREATE TABLE achievements_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	code VARCHAR(48) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ach_v4 UNIQUE (channel_id, canonical_uid, code)
);
CREATE TABLE action_logs_v5 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	response VARCHAR(1000) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE businesses_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	level INTEGER NOT NULL, 
	xp INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_business_v4 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE collection_set_claims_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	set_key VARCHAR(48) NOT NULL, 
	claimed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_collection_set_v55 UNIQUE (channel_id, canonical_uid, set_key)
);
CREATE TABLE collection_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	item_key VARCHAR(64) NOT NULL, 
	item_name VARCHAR(96) NOT NULL, 
	qty INTEGER NOT NULL, 
	first_found DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_collection_v54 UNIQUE (channel_id, canonical_uid, item_key)
);
CREATE TABLE community_meals_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	day INTEGER NOT NULL, 
	contributions INTEGER NOT NULL, 
	completed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_meal_v54 UNIQUE (channel_id, day)
);
CREATE TABLE cooldowns_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	ready_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cooldown_v52 UNIQUE (channel_id, canonical_uid, action)
);
CREATE TABLE craft_ledger_v581 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	recipe VARCHAR(64) NOT NULL, 
	qty INTEGER NOT NULL, 
	best_quality VARCHAR(24) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_craft_ledger_v581 UNIQUE (channel_id, canonical_uid, recipe)
);
CREATE TABLE daily_contracts_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	day_key VARCHAR(16) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	target INTEGER NOT NULL, 
	progress INTEGER NOT NULL, 
	reward_sc INTEGER NOT NULL, 
	complete BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_daily_v4 UNIQUE (channel_id, canonical_uid, day_key)
);
CREATE TABLE daily_variety_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	avesta_day INTEGER NOT NULL, 
	skills VARCHAR(240) NOT NULL, 
	claimed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_daily_variety_v600 UNIQUE (channel_id, canonical_uid, avesta_day)
);
CREATE TABLE determination_v581 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	skill VARCHAR(32) NOT NULL, 
	stacks INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_determination_v581 UNIQUE (channel_id, canonical_uid, skill)
);
CREATE TABLE directive_participants_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	avesta_day INTEGER NOT NULL, 
	contributions INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_directive_participant_v600 UNIQUE (channel_id, canonical_uid, avesta_day)
);
CREATE TABLE duck_bonds_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	duck VARCHAR(32) NOT NULL, 
	xp INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_duck_bond_v55 UNIQUE (channel_id, canonical_uid, duck)
);
CREATE TABLE event_contributions_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	event_instance VARCHAR(32) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	display_name VARCHAR(80) NOT NULL, 
	primary_successes INTEGER NOT NULL, 
	support_successes INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_event_contribution_v52 UNIQUE (channel_id, event_instance, canonical_uid)
);
CREATE TABLE event_history_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	event_instance VARCHAR(32) NOT NULL, 
	event_key VARCHAR(32) NOT NULL, 
	event_name VARCHAR(80) NOT NULL, 
	result VARCHAR(16) NOT NULL, 
	progress INTEGER NOT NULL, 
	goal INTEGER NOT NULL, 
	participants INTEGER NOT NULL, 
	started_by VARCHAR(128) NOT NULL, 
	ended_by VARCHAR(128) NOT NULL, 
	outcome VARCHAR(500) NOT NULL, 
	started_at DATETIME, 
	ended_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE extra_items_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	item VARCHAR(48) NOT NULL, 
	qty INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_item_v4 UNIQUE (channel_id, canonical_uid, item)
);
CREATE TABLE gear_familiarity_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	item_key VARCHAR(64) NOT NULL, 
	uses INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gear_familiarity_v600 UNIQUE (channel_id, canonical_uid, item_key)
);
CREATE TABLE hobby_progress_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	hobby VARCHAR(32) NOT NULL, 
	points INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_hobby_progress_v55 UNIQUE (channel_id, canonical_uid, hobby)
);
CREATE TABLE homes_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	tier INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_home_v4 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE identity_links_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	provider_uid VARCHAR(96) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_identity_v4 UNIQUE (channel_id, provider, provider_uid)
);
CREATE TABLE journal_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	entry VARCHAR(220) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE life_relationships_v53 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	uid_a VARCHAR(96) NOT NULL, 
	uid_b VARCHAR(96) NOT NULL, 
	familiarity INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_life_relationship_v53 UNIQUE (channel_id, uid_a, uid_b)
);
CREATE TABLE life_state_v53 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	energy INTEGER NOT NULL, 
	nutrition INTEGER NOT NULL, 
	social INTEGER NOT NULL, 
	comfort INTEGER NOT NULL, 
	morale INTEGER NOT NULL, 
	gardening INTEGER NOT NULL, 
	exploration_hobby INTEGER NOT NULL, 
	mechanics INTEGER NOT NULL, 
	research_hobby INTEGER NOT NULL, 
	games_hobby INTEGER NOT NULL, 
	rockwatching INTEGER NOT NULL, 
	last_decay_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_life_state_v53 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE link_codes_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	code VARCHAR(12) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
CREATE TABLE lore_discoveries_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	lore_key VARCHAR(64) NOT NULL, 
	discovered_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_lore_discovery_v600 UNIQUE (channel_id, canonical_uid, lore_key)
);
CREATE TABLE market_sales_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	avesta_day INTEGER NOT NULL, 
	resource VARCHAR(32) NOT NULL, 
	qty INTEGER NOT NULL, 
	sc_earned INTEGER NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE moderator_audit_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	moderator VARCHAR(128) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	detail VARCHAR(500) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE player_goals_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	day INTEGER NOT NULL, 
	goal_key VARCHAR(48) NOT NULL, 
	progress INTEGER NOT NULL, 
	claimed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_goal_v54 UNIQUE (channel_id, canonical_uid, day)
);
CREATE TABLE player_preferences_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	result_style VARCHAR(16) NOT NULL, 
	assigned_duck VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_player_preferences_v600 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE player_titles_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	title_key VARCHAR(48) NOT NULL, 
	unlocked_at DATETIME NOT NULL, 
	equipped BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_player_title_v55 UNIQUE (channel_id, canonical_uid, title_key)
);
CREATE TABLE player_world_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	district VARCHAR(48) NOT NULL, 
	shift_role VARCHAR(48) NOT NULL, 
	shift_day INTEGER NOT NULL, 
	siro_exposure INTEGER NOT NULL, 
	current_goal VARCHAR(48) NOT NULL, 
	goal_progress INTEGER NOT NULL, 
	goal_day INTEGER NOT NULL, 
	mentor_day INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_player_world_v54 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE players (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	twitch_uid VARCHAR(96) NOT NULL, 
	display_name VARCHAR(80) NOT NULL, 
	job VARCHAR(32) NOT NULL, 
	sc INTEGER NOT NULL, 
	contribution INTEGER NOT NULL, 
	farm_xp INTEGER NOT NULL, 
	mining_xp INTEGER NOT NULL, 
	industry_xp INTEGER NOT NULL, 
	research_xp INTEGER NOT NULL, 
	delivery_xp INTEGER NOT NULL, 
	explore_xp INTEGER NOT NULL, 
	environmental_xp INTEGER NOT NULL, 
	fabrication_xp INTEGER NOT NULL, 
	infrastructure_xp INTEGER NOT NULL, 
	commerce_xp INTEGER NOT NULL, 
	crops INTEGER NOT NULL, 
	ore INTEGER NOT NULL, 
	rare_ore INTEGER NOT NULL, 
	components INTEGER NOT NULL, 
	cargo INTEGER NOT NULL, 
	actions INTEGER NOT NULL, 
	successes INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_seen DATETIME NOT NULL, 
	last_job_change DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_player_channel_uid UNIQUE (channel_id, twitch_uid)
);
CREATE TABLE production_order_completions_v581 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	avesta_day INTEGER NOT NULL, 
	order_key VARCHAR(64) NOT NULL, 
	completed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_production_order_v581 UNIQUE (channel_id, canonical_uid, avesta_day, order_key)
);
CREATE TABLE quality_gear_v53 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	item_key VARCHAR(64) NOT NULL, 
	item_name VARCHAR(96) NOT NULL, 
	quality VARCHAR(24) NOT NULL, 
	qty INTEGER NOT NULL, 
	condition INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_quality_gear_v53 UNIQUE (channel_id, canonical_uid, item_key, quality)
);
CREATE TABLE relationship_memories_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	uid_a VARCHAR(96) NOT NULL, 
	uid_b VARCHAR(96) NOT NULL, 
	interactions INTEGER NOT NULL, 
	last_activity VARCHAR(48) NOT NULL, 
	last_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_relationship_memory_v600 UNIQUE (channel_id, uid_a, uid_b)
);
CREATE TABLE societies (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	food INTEGER NOT NULL, 
	materials INTEGER NOT NULL, 
	development INTEGER NOT NULL, 
	knowledge INTEGER NOT NULL, 
	treasury INTEGER NOT NULL, 
	reputation INTEGER NOT NULL, 
	population INTEGER NOT NULL, 
	day INTEGER NOT NULL, 
	siro_event BOOLEAN NOT NULL, 
	food_crisis BOOLEAN NOT NULL, 
	mining_boom BOOLEAN NOT NULL, 
	delivery_surge BOOLEAN NOT NULL, 
	market_boom BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE society_aftermath_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	event_name VARCHAR(80) NOT NULL, 
	result VARCHAR(16) NOT NULL, 
	skills VARCHAR(160) NOT NULL, 
	modifier INTEGER NOT NULL, 
	description VARCHAR(220) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE society_directives_v600 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	avesta_day INTEGER NOT NULL, 
	directive_key VARCHAR(48) NOT NULL, 
	progress INTEGER NOT NULL, 
	goal INTEGER NOT NULL, 
	complete BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_society_directive_v600 UNIQUE (channel_id, avesta_day)
);
CREATE TABLE society_projects_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	project_key VARCHAR(48) NOT NULL, 
	progress INTEGER NOT NULL, 
	goal INTEGER NOT NULL, 
	started_day INTEGER NOT NULL, 
	completed INTEGER NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE specializations_v52 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	skill VARCHAR(32) NOT NULL, 
	choice VARCHAR(48) NOT NULL, 
	chosen_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_specialization_v52 UNIQUE (channel_id, canonical_uid, skill)
);
CREATE TABLE status_effects_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	effect VARCHAR(64) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	modifier INTEGER NOT NULL, 
	description VARCHAR(160) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_status_v54 UNIQUE (channel_id, canonical_uid, effect)
);
CREATE TABLE timed_bonuses_v524 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	bonus VARCHAR(48) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	times_received INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_timed_bonus_v524 UNIQUE (channel_id, canonical_uid, bonus)
);
CREATE TABLE tutorial_progress_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	canonical_uid VARCHAR(96) NOT NULL, 
	step INTEGER NOT NULL, 
	completed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tutorial_v55 UNIQUE (channel_id, canonical_uid)
);
CREATE TABLE weekly_story_v55 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	week_index INTEGER NOT NULL, 
	arc_key VARCHAR(48) NOT NULL, 
	track_a INTEGER NOT NULL, 
	track_b INTEGER NOT NULL, 
	track_c INTEGER NOT NULL, 
	resolved BOOLEAN NOT NULL, 
	outcome VARCHAR(240) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_week_story_v55 UNIQUE (channel_id, week_index)
);
CREATE TABLE world_clock_v54 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	anchor_at DATETIME NOT NULL, 
	anchor_day INTEGER NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE world_v4 (
	id INTEGER NOT NULL, 
	channel_id VARCHAR(64) NOT NULL, 
	heartbeat DATETIME, 
	active_event VARCHAR(32), 
	event_progress INTEGER NOT NULL, 
	event_goal INTEGER NOT NULL, 
	event_ends DATETIME, 
	last_event_end DATETIME, 
	event_support_successes INTEGER NOT NULL, 
	event_instance VARCHAR(32), 
	event_started_at DATETIME, 
	event_started_by VARCHAR(128), 
	event_active_players INTEGER NOT NULL, 
	activity_since_event INTEGER NOT NULL, 
	activity_window_started_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_players_twitch_uid ON players (twitch_uid);
CREATE INDEX ix_players_channel_id ON players (channel_id);
CREATE UNIQUE INDEX ix_societies_channel_id ON societies (channel_id);
CREATE INDEX ix_identity_links_v4_canonical_uid ON identity_links_v4 (canonical_uid);
CREATE INDEX ix_identity_links_v4_channel_id ON identity_links_v4 (channel_id);
CREATE INDEX ix_link_codes_v4_channel_id ON link_codes_v4 (channel_id);
CREATE INDEX ix_extra_items_v4_channel_id ON extra_items_v4 (channel_id);
CREATE INDEX ix_extra_items_v4_canonical_uid ON extra_items_v4 (canonical_uid);
CREATE INDEX ix_daily_contracts_v4_channel_id ON daily_contracts_v4 (channel_id);
CREATE INDEX ix_daily_contracts_v4_canonical_uid ON daily_contracts_v4 (canonical_uid);
CREATE INDEX ix_homes_v4_canonical_uid ON homes_v4 (canonical_uid);
CREATE INDEX ix_homes_v4_channel_id ON homes_v4 (channel_id);
CREATE INDEX ix_businesses_v4_canonical_uid ON businesses_v4 (canonical_uid);
CREATE INDEX ix_businesses_v4_channel_id ON businesses_v4 (channel_id);
CREATE INDEX ix_achievements_v4_channel_id ON achievements_v4 (channel_id);
CREATE INDEX ix_achievements_v4_canonical_uid ON achievements_v4 (canonical_uid);
CREATE UNIQUE INDEX ix_world_v4_channel_id ON world_v4 (channel_id);
CREATE INDEX ix_action_logs_v5_channel_id ON action_logs_v5 (channel_id);
CREATE INDEX ix_action_logs_v5_canonical_uid ON action_logs_v5 (canonical_uid);
CREATE INDEX ix_cooldowns_v52_canonical_uid ON cooldowns_v52 (canonical_uid);
CREATE INDEX ix_cooldowns_v52_channel_id ON cooldowns_v52 (channel_id);
CREATE INDEX ix_account_links_v52_channel_id ON account_links_v52 (channel_id);
CREATE INDEX ix_account_name_history_v541_channel_id ON account_name_history_v541 (channel_id);
CREATE INDEX ix_account_name_history_v541_provider ON account_name_history_v541 (provider);
CREATE INDEX ix_account_name_history_v541_provider_uid ON account_name_history_v541 (provider_uid);
CREATE INDEX ix_hobby_progress_v55_canonical_uid ON hobby_progress_v55 (canonical_uid);
CREATE INDEX ix_hobby_progress_v55_channel_id ON hobby_progress_v55 (channel_id);
CREATE INDEX ix_weekly_story_v55_channel_id ON weekly_story_v55 (channel_id);
CREATE INDEX ix_collection_set_claims_v55_channel_id ON collection_set_claims_v55 (channel_id);
CREATE INDEX ix_collection_set_claims_v55_canonical_uid ON collection_set_claims_v55 (canonical_uid);
CREATE INDEX ix_player_titles_v55_canonical_uid ON player_titles_v55 (canonical_uid);
CREATE INDEX ix_player_titles_v55_channel_id ON player_titles_v55 (channel_id);
CREATE INDEX ix_market_sales_v55_canonical_uid ON market_sales_v55 (canonical_uid);
CREATE INDEX ix_market_sales_v55_channel_id ON market_sales_v55 (channel_id);
CREATE INDEX ix_duck_bonds_v55_channel_id ON duck_bonds_v55 (channel_id);
CREATE INDEX ix_duck_bonds_v55_canonical_uid ON duck_bonds_v55 (canonical_uid);
CREATE INDEX ix_tutorial_progress_v55_channel_id ON tutorial_progress_v55 (channel_id);
CREATE INDEX ix_tutorial_progress_v55_canonical_uid ON tutorial_progress_v55 (canonical_uid);
CREATE INDEX ix_specializations_v52_channel_id ON specializations_v52 (channel_id);
CREATE INDEX ix_specializations_v52_canonical_uid ON specializations_v52 (canonical_uid);
CREATE INDEX ix_event_contributions_v52_event_instance ON event_contributions_v52 (event_instance);
CREATE INDEX ix_event_contributions_v52_channel_id ON event_contributions_v52 (channel_id);
CREATE INDEX ix_event_contributions_v52_canonical_uid ON event_contributions_v52 (canonical_uid);
CREATE INDEX ix_event_history_v52_channel_id ON event_history_v52 (channel_id);
CREATE INDEX ix_event_history_v52_event_instance ON event_history_v52 (event_instance);
CREATE INDEX ix_moderator_audit_v52_channel_id ON moderator_audit_v52 (channel_id);
CREATE INDEX ix_timed_bonuses_v524_canonical_uid ON timed_bonuses_v524 (canonical_uid);
CREATE INDEX ix_timed_bonuses_v524_channel_id ON timed_bonuses_v524 (channel_id);
CREATE INDEX ix_life_state_v53_channel_id ON life_state_v53 (channel_id);
CREATE INDEX ix_life_state_v53_canonical_uid ON life_state_v53 (canonical_uid);
CREATE INDEX ix_quality_gear_v53_channel_id ON quality_gear_v53 (channel_id);
CREATE INDEX ix_quality_gear_v53_canonical_uid ON quality_gear_v53 (canonical_uid);
CREATE INDEX ix_life_relationships_v53_uid_a ON life_relationships_v53 (uid_a);
CREATE INDEX ix_life_relationships_v53_uid_b ON life_relationships_v53 (uid_b);
CREATE INDEX ix_life_relationships_v53_channel_id ON life_relationships_v53 (channel_id);
CREATE UNIQUE INDEX ix_world_clock_v54_channel_id ON world_clock_v54 (channel_id);
CREATE INDEX ix_player_world_v54_channel_id ON player_world_v54 (channel_id);
CREATE INDEX ix_player_world_v54_canonical_uid ON player_world_v54 (canonical_uid);
CREATE INDEX ix_collection_v54_channel_id ON collection_v54 (channel_id);
CREATE INDEX ix_collection_v54_canonical_uid ON collection_v54 (canonical_uid);
CREATE INDEX ix_status_effects_v54_channel_id ON status_effects_v54 (channel_id);
CREATE INDEX ix_status_effects_v54_canonical_uid ON status_effects_v54 (canonical_uid);
CREATE INDEX ix_player_goals_v54_channel_id ON player_goals_v54 (channel_id);
CREATE INDEX ix_player_goals_v54_canonical_uid ON player_goals_v54 (canonical_uid);
CREATE UNIQUE INDEX ix_society_projects_v54_channel_id ON society_projects_v54 (channel_id);
CREATE INDEX ix_community_meals_v54_channel_id ON community_meals_v54 (channel_id);
CREATE INDEX ix_journal_v54_canonical_uid ON journal_v54 (canonical_uid);
CREATE INDEX ix_journal_v54_channel_id ON journal_v54 (channel_id);
CREATE INDEX ix_determination_v581_canonical_uid ON determination_v581 (canonical_uid);
CREATE INDEX ix_determination_v581_channel_id ON determination_v581 (channel_id);
CREATE INDEX ix_production_order_completions_v581_canonical_uid ON production_order_completions_v581 (canonical_uid);
CREATE INDEX ix_production_order_completions_v581_channel_id ON production_order_completions_v581 (channel_id);
CREATE INDEX ix_craft_ledger_v581_canonical_uid ON craft_ledger_v581 (canonical_uid);
CREATE INDEX ix_craft_ledger_v581_channel_id ON craft_ledger_v581 (channel_id);
CREATE INDEX ix_player_preferences_v600_channel_id ON player_preferences_v600 (channel_id);
CREATE INDEX ix_player_preferences_v600_canonical_uid ON player_preferences_v600 (canonical_uid);
CREATE INDEX ix_daily_variety_v600_channel_id ON daily_variety_v600 (channel_id);
CREATE INDEX ix_daily_variety_v600_canonical_uid ON daily_variety_v600 (canonical_uid);
CREATE INDEX ix_society_directives_v600_channel_id ON society_directives_v600 (channel_id);
CREATE INDEX ix_directive_participants_v600_channel_id ON directive_participants_v600 (channel_id);
CREATE INDEX ix_directive_participants_v600_canonical_uid ON directive_participants_v600 (canonical_uid);
CREATE INDEX ix_society_aftermath_v600_channel_id ON society_aftermath_v600 (channel_id);
CREATE INDEX ix_gear_familiarity_v600_canonical_uid ON gear_familiarity_v600 (canonical_uid);
CREATE INDEX ix_gear_familiarity_v600_channel_id ON gear_familiarity_v600 (channel_id);
CREATE INDEX ix_relationship_memories_v600_channel_id ON relationship_memories_v600 (channel_id);
CREATE INDEX ix_relationship_memories_v600_uid_b ON relationship_memories_v600 (uid_b);
CREATE INDEX ix_relationship_memories_v600_uid_a ON relationship_memories_v600 (uid_a);
CREATE INDEX ix_lore_discoveries_v600_canonical_uid ON lore_discoveries_v600 (canonical_uid);
CREATE INDEX ix_lore_discoveries_v600_channel_id ON lore_discoveries_v600 (channel_id);
COMMIT;