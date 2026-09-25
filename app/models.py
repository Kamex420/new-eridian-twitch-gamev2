
"""Persistence models. Legacy table and column names are intentional compatibility contracts."""
import os
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, UniqueConstraint, Float
from .db import Base
GAME_NAME=os.getenv("GAME_NAME", "New Eridian")
def now(): return datetime.now(timezone.utc)
class Player(Base):
    __tablename__="players"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    twitch_uid=Column(String(96),nullable=False,index=True)
    display_name=Column(String(80),nullable=False,default="Citizen")
    job=Column(String(32),nullable=False,default="settler")
    sc=Column(Integer,nullable=False,default=10)
    contribution=Column(Integer,nullable=False,default=0)
    farm_xp=Column(Integer,nullable=False,default=0)
    mining_xp=Column(Integer,nullable=False,default=0)
    industry_xp=Column(Integer,nullable=False,default=0)
    research_xp=Column(Integer,nullable=False,default=0)
    delivery_xp=Column(Integer,nullable=False,default=0)
    explore_xp=Column(Integer,nullable=False,default=0)
    environmental_xp=Column(Integer,nullable=False,default=0)
    fabrication_xp=Column(Integer,nullable=False,default=0)
    infrastructure_xp=Column(Integer,nullable=False,default=0)
    commerce_xp=Column(Integer,nullable=False,default=0)
    cooking_xp=Column(Integer,nullable=False,default=0)
    medicine_xp=Column(Integer,nullable=False,default=0)
    emergency_xp=Column(Integer,nullable=False,default=0)
    crops=Column(Integer,nullable=False,default=0)
    ore=Column(Integer,nullable=False,default=0)
    rare_ore=Column(Integer,nullable=False,default=0)
    components=Column(Integer,nullable=False,default=0)
    cargo=Column(Integer,nullable=False,default=0)
    actions=Column(Integer,nullable=False,default=0)
    successes=Column(Integer,nullable=False,default=0)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)
    last_seen=Column(DateTime(timezone=True),default=now,nullable=False)
    last_job_change=Column(DateTime(timezone=True),nullable=True)
    __table_args__=(UniqueConstraint("channel_id","twitch_uid",name="uq_player_channel_uid"),)

class Society(Base):
    __tablename__="societies"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,unique=True,index=True)
    name=Column(String(80),nullable=False,default=GAME_NAME)
    food=Column(Integer,nullable=False,default=0)
    materials=Column(Integer,nullable=False,default=0)
    development=Column(Integer,nullable=False,default=0)
    knowledge=Column(Integer,nullable=False,default=0)
    treasury=Column(Integer,nullable=False,default=0)
    reputation=Column(Integer,nullable=False,default=0)
    population=Column(Integer,nullable=False,default=0)
    day=Column(Integer,nullable=False,default=1)
    siro_event=Column(Boolean,nullable=False,default=False)
    food_crisis=Column(Boolean,nullable=False,default=False)
    mining_boom=Column(Boolean,nullable=False,default=False)
    delivery_surge=Column(Boolean,nullable=False,default=False)
    market_boom=Column(Boolean,nullable=False,default=False)

class Identity(Base):
    __tablename__="identity_links_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    provider=Column(String(16),nullable=False)
    provider_uid=Column(String(96),nullable=False)
    canonical_uid=Column(String(96),nullable=False,index=True)
    __table_args__=(UniqueConstraint("channel_id","provider","provider_uid",name="uq_identity_v4"),)

class LinkCode(Base):
    __tablename__="link_codes_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False)
    code=Column(String(12),nullable=False,unique=True)
    expires_at=Column(DateTime(timezone=True),nullable=False)

class ExtraItem(Base):
    __tablename__="extra_items_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    item=Column(String(48),nullable=False)
    qty=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","item",name="uq_item_v4"),)

class Daily(Base):
    __tablename__="daily_contracts_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    day_key=Column(String(16),nullable=False)
    action=Column(String(32),nullable=False)
    target=Column(Integer,nullable=False)
    progress=Column(Integer,nullable=False,default=0)
    reward_sc=Column(Integer,nullable=False)
    complete=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","day_key",name="uq_daily_v4"),)

class Home(Base):
    __tablename__="homes_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    tier=Column(Integer,nullable=False,default=1)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_home_v4"),)

class Business(Base):
    __tablename__="businesses_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    name=Column(String(80),nullable=False)
    level=Column(Integer,nullable=False,default=1)
    xp=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_business_v4"),)

class Achievement(Base):
    __tablename__="achievements_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    code=Column(String(48),nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","code",name="uq_ach_v4"),)

class World(Base):
    __tablename__="world_v4"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,unique=True,index=True)
    heartbeat=Column(DateTime(timezone=True),nullable=True)
    active_event=Column(String(32),nullable=True)
    event_progress=Column(Integer,nullable=False,default=0)
    event_goal=Column(Integer,nullable=False,default=0)
    event_ends=Column(DateTime(timezone=True),nullable=True)
    last_event_end=Column(DateTime(timezone=True),nullable=True)
    event_support_successes=Column(Integer,nullable=False,default=0)
    event_instance=Column(String(32),nullable=True)
    event_started_at=Column(DateTime(timezone=True),nullable=True)
    event_started_by=Column(String(128),nullable=True)
    event_active_players=Column(Integer,nullable=False,default=1)
    activity_since_event=Column(Integer,nullable=False,default=0)
    activity_window_started_at=Column(DateTime(timezone=True),nullable=True)

class ActionLog(Base):
    __tablename__="action_logs_v5"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    action=Column(String(64),nullable=False)
    response=Column(String(1000),nullable=False)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)

class Cooldown(Base):
    __tablename__="cooldowns_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    action=Column(String(64),nullable=False)
    ready_at=Column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","action",name="uq_cooldown_v52"),)

class AccountLink(Base):
    __tablename__="account_links_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    twitch_uid=Column(String(96),nullable=False)
    discord_uid=Column(String(96),nullable=False)
    linked_at=Column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(UniqueConstraint("channel_id","twitch_uid",name="uq_link_twitch_v52"),UniqueConstraint("channel_id","discord_uid",name="uq_link_discord_v52"))

class AccountNameHistory(Base):
    __tablename__="account_name_history_v541"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    provider=Column(String(16),nullable=False,index=True)
    provider_uid=Column(String(96),nullable=False,index=True)
    display_name=Column(String(80),nullable=False)
    first_seen=Column(DateTime(timezone=True),default=now,nullable=False)
    last_seen=Column(DateTime(timezone=True),default=now,nullable=False)
    seen_count=Column(Integer,nullable=False,default=1)
    __table_args__=(UniqueConstraint("channel_id","provider","provider_uid","display_name",name="uq_name_history_v541"),)


class HobbyProgress(Base):
    __tablename__="hobby_progress_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    hobby=Column(String(32),nullable=False)
    points=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","hobby",name="uq_hobby_progress_v55"),)

class WeeklyStory(Base):
    __tablename__="weekly_story_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    week_index=Column(Integer,nullable=False)
    arc_key=Column(String(48),nullable=False)
    track_a=Column(Integer,nullable=False,default=0)
    track_b=Column(Integer,nullable=False,default=0)
    track_c=Column(Integer,nullable=False,default=0)
    resolved=Column(Boolean,nullable=False,default=False)
    outcome=Column(String(240),nullable=False,default="")
    __table_args__=(UniqueConstraint("channel_id","week_index",name="uq_week_story_v55"),)

class CollectionSetClaim(Base):
    __tablename__="collection_set_claims_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    set_key=Column(String(48),nullable=False)
    claimed_at=Column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","set_key",name="uq_collection_set_v55"),)

class PlayerTitle(Base):
    __tablename__="player_titles_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    title_key=Column(String(48),nullable=False)
    unlocked_at=Column(DateTime(timezone=True),default=now,nullable=False)
    equipped=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","title_key",name="uq_player_title_v55"),)

class MarketSale(Base):
    __tablename__="market_sales_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    avesta_day=Column(Integer,nullable=False)
    resource=Column(String(32),nullable=False)
    qty=Column(Integer,nullable=False,default=0)
    sc_earned=Column(Integer,nullable=False,default=0)

class DuckBond(Base):
    __tablename__="duck_bonds_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    duck=Column(String(32),nullable=False)
    xp=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","duck",name="uq_duck_bond_v55"),)

class TutorialProgress(Base):
    __tablename__="tutorial_progress_v55"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    step=Column(Integer,nullable=False,default=0)
    completed=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_tutorial_v55"),)

class Specialization(Base):
    __tablename__="specializations_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    skill=Column(String(32),nullable=False)
    choice=Column(String(48),nullable=False)
    chosen_at=Column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","skill",name="uq_specialization_v52"),)

class EventContribution(Base):
    __tablename__="event_contributions_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    event_instance=Column(String(32),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    display_name=Column(String(80),nullable=False,default="Citizen")
    primary_successes=Column(Integer,nullable=False,default=0)
    support_successes=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","event_instance","canonical_uid",name="uq_event_contribution_v52"),)

class EventHistory(Base):
    __tablename__="event_history_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    event_instance=Column(String(32),nullable=False,index=True)
    event_key=Column(String(32),nullable=False)
    event_name=Column(String(80),nullable=False)
    result=Column(String(16),nullable=False)
    progress=Column(Integer,nullable=False,default=0)
    goal=Column(Integer,nullable=False,default=0)
    participants=Column(Integer,nullable=False,default=0)
    started_by=Column(String(128),nullable=False,default="automatic")
    ended_by=Column(String(128),nullable=False,default="system")
    outcome=Column(String(500),nullable=False,default="")
    started_at=Column(DateTime(timezone=True),nullable=True)
    ended_at=Column(DateTime(timezone=True),default=now,nullable=False)

class ModeratorAudit(Base):
    __tablename__="moderator_audit_v52"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    moderator=Column(String(128),nullable=False)
    action=Column(String(64),nullable=False)
    detail=Column(String(500),nullable=False)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)

class TimedBonus(Base):
    __tablename__="timed_bonuses_v524"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    bonus=Column(String(48),nullable=False)
    expires_at=Column(DateTime(timezone=True),nullable=False)
    times_received=Column(Integer,nullable=False,default=1)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","bonus",name="uq_timed_bonus_v524"),)


class LifeState(Base):
    __tablename__="life_state_v53"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    energy=Column(Integer,nullable=False,default=80)
    nutrition=Column(Integer,nullable=False,default=70)
    social=Column(Integer,nullable=False,default=60)
    comfort=Column(Integer,nullable=False,default=60)
    morale=Column(Integer,nullable=False,default=60)
    gardening=Column(Integer,nullable=False,default=0)
    exploration_hobby=Column(Integer,nullable=False,default=0)
    mechanics=Column(Integer,nullable=False,default=0)
    research_hobby=Column(Integer,nullable=False,default=0)
    games_hobby=Column(Integer,nullable=False,default=0)
    rockwatching=Column(Integer,nullable=False,default=0)
    last_decay_at=Column(DateTime(timezone=True),default=now,nullable=False)
    updated_at=Column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_life_state_v53"),)

class QualityGear(Base):
    __tablename__="quality_gear_v53"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    item_key=Column(String(64),nullable=False)
    item_name=Column(String(96),nullable=False)
    quality=Column(String(24),nullable=False,default="Standard")
    qty=Column(Integer,nullable=False,default=1)
    condition=Column(Integer,nullable=False,default=100)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","item_key","quality",name="uq_quality_gear_v53"),)

class LifeRelationship(Base):
    __tablename__="life_relationships_v53"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    uid_a=Column(String(96),nullable=False,index=True)
    uid_b=Column(String(96),nullable=False,index=True)
    familiarity=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","uid_a","uid_b",name="uq_life_relationship_v53"),)


class WorldClock(Base):
    __tablename__="world_clock_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,unique=True,index=True)
    anchor_at=Column(DateTime(timezone=True),nullable=False,default=now)
    anchor_day=Column(Integer,nullable=False,default=1)

class PlayerWorld(Base):
    __tablename__="player_world_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    district=Column(String(48),nullable=False,default="residential_ring")
    shift_role=Column(String(48),nullable=False,default="off_duty")
    shift_day=Column(Integer,nullable=False,default=0)
    siro_exposure=Column(Integer,nullable=False,default=0)
    current_goal=Column(String(48),nullable=False,default="")
    goal_progress=Column(Integer,nullable=False,default=0)
    goal_day=Column(Integer,nullable=False,default=0)
    mentor_day=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_player_world_v54"),)

class CollectionItem(Base):
    __tablename__="collection_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    item_key=Column(String(64),nullable=False)
    item_name=Column(String(96),nullable=False)
    qty=Column(Integer,nullable=False,default=0)
    first_found=Column(DateTime(timezone=True),nullable=False,default=now)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","item_key",name="uq_collection_v54"),)

class StatusEffect(Base):
    __tablename__="status_effects_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    effect=Column(String(64),nullable=False)
    expires_at=Column(DateTime(timezone=True),nullable=False)
    modifier=Column(Integer,nullable=False,default=0)
    description=Column(String(160),nullable=False,default="")
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","effect",name="uq_status_v54"),)

class PlayerGoal(Base):
    __tablename__="player_goals_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    day=Column(Integer,nullable=False)
    goal_key=Column(String(48),nullable=False)
    progress=Column(Integer,nullable=False,default=0)
    claimed=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","day",name="uq_goal_v54"),)

class SocietyProject(Base):
    __tablename__="society_projects_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,unique=True,index=True)
    project_key=Column(String(48),nullable=False,default="greenhouse_expansion")
    progress=Column(Integer,nullable=False,default=0)
    goal=Column(Integer,nullable=False,default=50)
    started_day=Column(Integer,nullable=False,default=1)
    completed=Column(Integer,nullable=False,default=0)

class CommunityMeal(Base):
    __tablename__="community_meals_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    day=Column(Integer,nullable=False)
    contributions=Column(Integer,nullable=False,default=0)
    completed=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","day",name="uq_meal_v54"),)

class JournalEntry(Base):
    __tablename__="journal_v54"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    entry=Column(String(220),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False,default=now)

class Determination(Base):
    __tablename__="determination_v581"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    skill=Column(String(32),nullable=False)
    stacks=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","skill",name="uq_determination_v581"),)

class ProductionOrderCompletion(Base):
    __tablename__="production_order_completions_v581"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    avesta_day=Column(Integer,nullable=False)
    order_key=Column(String(64),nullable=False)
    completed_at=Column(DateTime(timezone=True),nullable=False,default=now)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","avesta_day","order_key",name="uq_production_order_v581"),)

class CraftLedger(Base):
    __tablename__="craft_ledger_v581"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    recipe=Column(String(64),nullable=False)
    qty=Column(Integer,nullable=False,default=0)
    best_quality=Column(String(24),nullable=False,default="")
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","recipe",name="uq_craft_ledger_v581"),)

# v6.0 engagement systems intentionally add horizontal goals rather than a
# stronger success-chance ladder.  They reward variety, shared priorities,
# memories, and long-term attachment without invalidating existing balance.
class PlayerPreference(Base):
    __tablename__="player_preferences_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    result_style=Column(String(16),nullable=False,default="compact")
    assigned_duck=Column(String(32),nullable=False,default="")
    __table_args__=(UniqueConstraint("channel_id","canonical_uid",name="uq_player_preferences_v600"),)

class DailyVariety(Base):
    __tablename__="daily_variety_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    avesta_day=Column(Integer,nullable=False)
    skills=Column(String(240),nullable=False,default="")
    claimed=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","avesta_day",name="uq_daily_variety_v600"),)

class DirectiveProgress(Base):
    __tablename__="society_directives_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    avesta_day=Column(Integer,nullable=False)
    directive_key=Column(String(48),nullable=False)
    progress=Column(Integer,nullable=False,default=0)
    goal=Column(Integer,nullable=False,default=12)
    complete=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint("channel_id","avesta_day",name="uq_society_directive_v600"),)

class DirectiveParticipant(Base):
    __tablename__="directive_participants_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    avesta_day=Column(Integer,nullable=False)
    contributions=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","avesta_day",name="uq_directive_participant_v600"),)

class SocietyAftermath(Base):
    __tablename__="society_aftermath_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    event_name=Column(String(80),nullable=False)
    result=Column(String(16),nullable=False)
    skills=Column(String(160),nullable=False,default="")
    modifier=Column(Integer,nullable=False,default=0)
    description=Column(String(220),nullable=False,default="")
    expires_at=Column(DateTime(timezone=True),nullable=False)

class GearFamiliarity(Base):
    __tablename__="gear_familiarity_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    item_key=Column(String(64),nullable=False)
    uses=Column(Integer,nullable=False,default=0)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","item_key",name="uq_gear_familiarity_v600"),)

class RelationshipMemory(Base):
    __tablename__="relationship_memories_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    uid_a=Column(String(96),nullable=False,index=True)
    uid_b=Column(String(96),nullable=False,index=True)
    interactions=Column(Integer,nullable=False,default=0)
    last_activity=Column(String(48),nullable=False,default="Met")
    last_at=Column(DateTime(timezone=True),nullable=False,default=now)
    __table_args__=(UniqueConstraint("channel_id","uid_a","uid_b",name="uq_relationship_memory_v600"),)

class LoreDiscovery(Base):
    __tablename__="lore_discoveries_v600"
    id=Column(Integer,primary_key=True)
    channel_id=Column(String(64),nullable=False,index=True)
    canonical_uid=Column(String(96),nullable=False,index=True)
    lore_key=Column(String(64),nullable=False)
    discovered_at=Column(DateTime(timezone=True),nullable=False,default=now)
    __table_args__=(UniqueConstraint("channel_id","canonical_uid","lore_key",name="uq_lore_discovery_v600"),)


class SimulationVersion(Base):
    __tablename__="simulation_schema_versions"
    version=Column(Integer, primary_key=True)
    applied_at=Column(DateTime(timezone=True), default=now, nullable=False)

class SettlementState(Base):
    __tablename__="settlement_state_v7"
    channel_id=Column(String(64), primary_key=True)
    water=Column(Integer, nullable=False, default=20)
    ore=Column(Integer, nullable=False, default=0)
    rare_ore=Column(Integer, nullable=False, default=0)
    components=Column(Integer, nullable=False, default=0)
    medicines=Column(Integer, nullable=False, default=0)
    cargo=Column(Integer, nullable=False, default=0)
    infrastructure=Column(Integer, nullable=False, default=0)
    housing=Column(Integer, nullable=False, default=4)
    mood=Column(Integer, nullable=False, default=60)
    last_tick=Column(DateTime(timezone=True), default=now, nullable=False)

class SeedlingState(Base):
    __tablename__="seedling_state_v7"
    channel_id=Column(String(64), primary_key=True)
    canonical_uid=Column(String(96), primary_key=True)
    occupation_history=Column(String, nullable=False, default="[]")
    practice=Column(String, nullable=False, default="{}")
    routine=Column(String(32), nullable=False, default="balanced")
    preferred_activity=Column(String(32), nullable=False, default="games")
    goal=Column(String(32), nullable=False, default="settlement")
    last_progress=Column(String, nullable=False, default="")
    last_progress_at=Column(DateTime(timezone=True), nullable=True)

# Canonical vocabulary without duplicating player balances or identities.
Seedling=Player
Settlement=Society
Needs=LifeState

class SkillBranch(Base):
    __tablename__="skill_branches_v8"
    channel_id=Column(String(64),primary_key=True)
    canonical_uid=Column(String(96),primary_key=True)
    branch=Column(String(48),primary_key=True)
    xp=Column(Integer,nullable=False,default=0)
