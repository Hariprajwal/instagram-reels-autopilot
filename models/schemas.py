from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

class CommentIntent(str, Enum):
    EXPLICITLY_INTERESTED = "EXPLICITLY_INTERESTED"
    ASKING_FOR_INFO = "ASKING_FOR_INFO"
    PURCHASE_INTENT = "PURCHASE_INTENT"
    COLLABORATION = "COLLABORATION"
    CASUAL_ENGAGEMENT = "CASUAL_ENGAGEMENT"
    UNRELATED = "UNRELATED"
    UNCERTAIN = "UNCERTAIN"

class MessageAvailability(str, Enum):
    MESSAGE_BUTTON_VISIBLE = "MESSAGE_BUTTON_VISIBLE"
    MESSAGE_BUTTON_UNAVAILABLE = "MESSAGE_BUTTON_UNAVAILABLE"
    MESSAGING_RESTRICTED = "MESSAGING_RESTRICTED"
    PROFILE_INACCESSIBLE = "PROFILE_INACCESSIBLE"
    UNCERTAIN = "UNCERTAIN"

class DMPermission(str, Enum):
    EXPLICIT_INVITATION = "EXPLICIT_INVITATION"
    EXISTING_PERMISSION = "EXISTING_PERMISSION"
    NO_EXPLICIT_PERMISSION = "NO_EXPLICIT_PERMISSION"
    EXPLICIT_REFUSAL = "EXPLICIT_REFUSAL"

class DecisionClassification(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INTERESTED_BUT_NO_PERMISSION = "INTERESTED_BUT_NO_PERMISSION"
    NOT_INTERESTED = "NOT_INTERESTED"
    UNAVAILABLE = "UNAVAILABLE"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    UNCERTAIN = "UNCERTAIN"

class ReelContext(BaseModel):
    reel_id: str
    url: str
    author: Optional[str] = None
    caption: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    screenshot_path: Optional[str] = None

class CommentData(BaseModel):
    username: str
    text: str
    position_index: int
    reel_id: str
    timestamp: datetime = Field(default_factory=datetime.now)

class ProfileData(BaseModel):
    username: str
    is_private: bool = False
    message_button_found: bool = False
    message_availability: MessageAvailability = MessageAvailability.UNCERTAIN
    messaging_restrictions: Optional[str] = None
    bio_text: Optional[str] = None
    category: Optional[str] = None
    followers_count: Optional[str] = None
    is_accessible: bool = True
    screenshot_path: Optional[str] = None
    inspected_at: datetime = Field(default_factory=datetime.now)

class ProspectAnalysis(BaseModel):
    username: str
    reel_id: str
    comment_text: str
    comment_intent: CommentIntent
    profile_summary: Optional[str] = None
    message_availability: MessageAvailability
    dm_permission: DMPermission
    decision: DecisionClassification
    reasoning: str
    suggested_question: Optional[str] = None
    message_sequence: List[str] = Field(default_factory=list)
    approved_by_user: bool = False
    message_sent: bool = False
    analyzed_at: datetime = Field(default_factory=datetime.now)

class SessionStats(BaseModel):
    reels_inspected: int = 0
    comments_read: int = 0
    profiles_opened: int = 0
    profiles_with_message_buttons: int = 0
    explicit_dm_invitations: int = 0
    interested_without_dm_permission: int = 0
    unavailable_profiles: int = 0
    do_not_contact_profiles: int = 0
    eligible_conversations: int = 0
    questions_prepared: int = 0
    questions_sent: int = 0
    start_time: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

