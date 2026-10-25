"""Read current QQ website docs, never SDKs; no credentials or upstream API calls."""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import json
import re
from urllib.request import Request, urlopen

BASE = 'https://bot.q.qq.com/wiki/develop/api-v2/'
CHECKS = [
    ('GET', '/channels/{channel_id}/schedules', 'content/schedule/get_schedules'),
    ('GET', '/channels/{channel_id}/schedules/{schedule_id}', 'content/schedule/get_schedule'),
    ('PATCH', '/channels/{channel_id}/schedules/{schedule_id}', 'content/schedule/patch_schedule'),
    ('DELETE', '/channels/{channel_id}/schedules/{schedule_id}', 'content/schedule/delete_schedule'),
    ('GET', '/channels/{channel_id}/threads', 'content/forum/get_threads_list'),
    ('GET', '/channels/{channel_id}/threads/{thread_id}', 'content/forum/get_thread'),
    ('DELETE', '/channels/{channel_id}/threads/{thread_id}', 'content/forum/delete_thread'),
    ('POST', '/guilds/{guild_id}/announces', 'content/announces/post_guild_announces'),
    ('DELETE', '/guilds/{guild_id}/announces/{message_id}', 'content/announces/delete_guild_announces'),
    ('POST', '/channels/{channel_id}/announces', 'content/announces/post_channel_announces'),
    ('DELETE', '/channels/{channel_id}/announces/{message_id}', 'content/announces/delete_channel_announces'),
    ('GET', '/channels/{channel_id}/pins', 'content/pins/get_pins_message'),
    ('PUT', '/channels/{channel_id}/pins/{message_id}', 'content/pins/put_pins_message'),
    ('DELETE', '/channels/{channel_id}/pins/{message_id}', 'content/pins/delete_pins_message'),
    ('PUT', '/channels/{channel_id}/mic', 'content/audio/put_mic'),
    ('DELETE', '/channels/{channel_id}/mic', 'content/audio/delete_mic'),
    ('PATCH', '/guilds/{guild_id}/members/{user_id}/mute', 'speak/patch_guild_member_mute'),
    ('PATCH', '/guilds/{guild_id}/mute', 'speak/patch_guild_mute_multi_member'),
    ('GET', '/guilds/{guild_id}/api_permission', 'api_permissions/get_guild_api_permission'),
    ('GET', '/guilds/{guild_id}/roles/{role_id}/members', 'role/member/get_role_members'),
    ('GET', '/v2/groups/{group_openid}/info', 'autogen/api/v2_groups_group_openid_info.get'),
    ('GET', '/v2/groups/{group_openid}/members', 'autogen/api/v2_groups_group_openid_members.get'),
    ('GET', '/v2/groups/{group_openid}/members/{member_openid}', 'autogen/api/v2_groups_group_openid_members_member_openid.get'),
    ('POST', '/v2/groups/{group_openid}/batch_remove_members', 'autogen/api/v2_groups_group_openid_batch_remove_members.post'),
    ('POST', '/v2/groups/{group_openid}/restrict_chat_setting', 'autogen/api/v2_groups_group_openid_restrict_chat_setting.post'),
    ('POST', '/v2/groups/{group_openid}/approval_join_request/{member_openid}', 'autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post'),
]


def check(row):
    method, path, page = row
    generated = page.startswith('autogen/')
    url = BASE + ('' if generated else 'server-inter/channel/') + page + '.html'
    try:
        with urlopen(Request(url, headers={'User-Agent': 'QQ-Proxy-Documentation-Check/1'}), timeout=25) as response:
            raw = response.read(4_000_000).decode('utf-8')
        text = unescape(re.sub(r'<[^>]+>', '', raw))
        expected = method + ' ' + path
        verified = (bool(re.search(r'HTTP URL\s*' + re.escape(path) + r'\s*HTTP Method\s*' + method, text))
                    if generated else expected in text)
        return {'method': method, 'path': path, 'url': url,
                'verified': verified,
                'documented_operations': sorted(set(re.findall(r'(?:GET|POST|PUT|PATCH|DELETE)\s+/[\w/{}@-]+', text)))[:15]}
    except Exception as error:
        return {'method': method, 'path': path, 'url': url, 'verified': False, 'error': type(error).__name__}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=6) as executor:
        result = list(executor.map(check, CHECKS))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if all(row['verified'] for row in result) else 1)
