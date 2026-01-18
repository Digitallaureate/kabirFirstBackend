from firebase_functions import https_fn

@https_fn.on_request()
def device_redirect(req: https_fn.Request) -> https_fn.Response:
    user_agent = req.headers.get('User-Agent', '').lower()

    android_url = 'https://play.google.com/store/apps/details?id=com.kabirai.kabirv2&pcampaignid=web_share'
    ios_url = 'https://apps.apple.com/in/app/kabir-56/id6747632798'
    fallback_url = 'https://www.kabir-ai.com/'

    if 'android' in user_agent:
        return redirect(android_url)
    elif any(device in user_agent for device in ['iphone', 'ipad', 'ipod']):
        return redirect(ios_url)
    else:
        return redirect(fallback_url)


def redirect(url, code=302):
    from flask import make_response
    response = make_response('', code)
    response.headers['Location'] = url
    return response
