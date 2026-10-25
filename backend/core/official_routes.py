"""Official website-verified management operations, shared by API and capabilities.

Local scopes are not QQ OAuth scopes or Gateway intents. Unknown routes fail closed.
See scripts/check_official_docs.py for live website verification of additions.
"""
import re

ID = r'[A-Za-z0-9_-]{1,128}'
OPERATIONS = (
    ('GET', 'v2/groups/{group_openid}/info', 'groups:read'),
    ('GET', 'v2/groups/{group_openid}/members', 'group-members:read'),
    ('GET', 'v2/groups/{group_openid}/members/{member_openid}', 'group-members:read'),
    ('POST', 'v2/groups/{group_openid}/batch_remove_members', 'group-moderation:write'),
    ('POST', 'v2/groups/{group_openid}/restrict_chat_setting', 'group-moderation:write'),
    ('POST', 'v2/groups/{group_openid}/approval_join_request/{member_openid}', 'group-requests:write'),
    ('GET', 'guilds/{guild_id}', 'guilds:read'),
    ('GET', 'guilds/{guild_id}/channels', 'channels:read'),
    ('POST', 'guilds/{guild_id}/channels', 'channels:write'),
    ('GET', 'channels/{channel_id}', 'channels:read'),
    ('PATCH', 'channels/{channel_id}', 'channels:write'),
    ('DELETE', 'channels/{channel_id}', 'channels:write'),
    ('GET', 'guilds/{guild_id}/members', 'members:read'),
    ('GET', 'guilds/{guild_id}/members/{user_id}', 'members:read'),
    ('DELETE', 'guilds/{guild_id}/members/{user_id}', 'members:write'),
    ('GET', 'guilds/{guild_id}/roles/{role_id}/members', 'members:read'),
    ('GET', 'guilds/{guild_id}/roles', 'roles:read'),
    ('POST', 'guilds/{guild_id}/roles', 'roles:write'),
    ('PATCH', 'guilds/{guild_id}/roles/{role_id}', 'roles:write'),
    ('DELETE', 'guilds/{guild_id}/roles/{role_id}', 'roles:write'),
    ('PUT', 'guilds/{guild_id}/members/{user_id}/roles/{role_id}', 'roles:write'),
    ('DELETE', 'guilds/{guild_id}/members/{user_id}/roles/{role_id}', 'roles:write'),
    ('GET', 'channels/{channel_id}/members/{user_id}/permissions', 'permissions:read'),
    ('PUT', 'channels/{channel_id}/members/{user_id}/permissions', 'permissions:write'),
    ('GET', 'channels/{channel_id}/roles/{role_id}/permissions', 'permissions:read'),
    ('PUT', 'channels/{channel_id}/roles/{role_id}/permissions', 'permissions:write'),
    ('GET', 'channels/{channel_id}/schedules', 'schedules:read'),
    ('POST', 'channels/{channel_id}/schedules', 'schedules:write'),
    ('GET', 'channels/{channel_id}/schedules/{schedule_id}', 'schedules:read'),
    ('PATCH', 'channels/{channel_id}/schedules/{schedule_id}', 'schedules:write'),
    ('DELETE', 'channels/{channel_id}/schedules/{schedule_id}', 'schedules:write'),
    ('GET', 'channels/{channel_id}/threads', 'forums:read'),
    ('PUT', 'channels/{channel_id}/threads', 'forums:write'),
    ('GET', 'channels/{channel_id}/threads/{thread_id}', 'forums:read'),
    ('DELETE', 'channels/{channel_id}/threads/{thread_id}', 'forums:write'),
    ('POST', 'guilds/{guild_id}/announces', 'announcements:write'),
    ('DELETE', 'guilds/{guild_id}/announces/{message_id}', 'announcements:write'),
    ('POST', 'channels/{channel_id}/announces', 'announcements:write'),
    ('DELETE', 'channels/{channel_id}/announces/{message_id}', 'announcements:write'),
    ('GET', 'channels/{channel_id}/pins', 'pins:read'),
    ('PUT', 'channels/{channel_id}/pins/{message_id}', 'pins:write'),
    ('DELETE', 'channels/{channel_id}/pins/{message_id}', 'pins:write'),
    ('POST', 'channels/{channel_id}/audio', 'audio:control'),
    ('PUT', 'channels/{channel_id}/mic', 'audio:control'),
    ('DELETE', 'channels/{channel_id}/mic', 'audio:control'),
    ('PATCH', 'guilds/{guild_id}/mute', 'moderation:write'),
    ('PATCH', 'guilds/{guild_id}/members/{user_id}/mute', 'moderation:write'),
    ('GET', 'guilds/{guild_id}/api_permission', 'api-permissions:read'),
    ('POST', 'guilds/{guild_id}/api_permission/demand', 'api-permissions:write'),
)
ROUTES = tuple((method, re.sub(r'\{\w+\}', lambda _: ID, path), scope) for method, path, scope in OPERATIONS)


def required_scope(method, path):
    return next((scope for verb, pattern, scope in ROUTES if verb == method and re.fullmatch(pattern, path)), None)
