from pathlib import Path
import os
from playwright.sync_api import sync_playwright
out=Path(os.environ.get('M5_SCREENSHOT_DIR', '/workspace/abroj-dashboard-impl'))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
    context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
    page=context.new_page()
    page.add_init_script("""window.cameraCaptions = []; const originalSend = XMLHttpRequest.prototype.send; XMLHttpRequest.prototype.send = function(body) { if (body instanceof FormData && body.has('description')) window.cameraCaptions.push(body.get('description')); return originalSend.call(this, body); };""")
    page.on('pageerror',lambda e: print('PAGE ERROR',e))
    page.goto(os.environ.get('M5_BASE_URL', 'http://127.0.0.1:18964') + '/abroj/app')
    page.locator('[name=login]').fill(os.environ.get('M5_USER', 'owner'));page.locator('[name=password]').fill(os.environ.get('M5_PASSWORD', 'owner'));page.locator('button[type=submit]').click()
    page.wait_for_function('data && data.projects.length',timeout=60000)
    for lang in ('ar','en'):
        page.evaluate("lang => {localStorage.setItem('abroj.language',lang); location.reload()}",lang)
        page.wait_for_function('data && data.projects.length',timeout=60000)
        page.evaluate("detail(data.projects[0].id,'notes')");page.locator('.fab').wait_for()
        def shot(name):
            page.wait_for_timeout(400)
            page.screenshot(path=str(out / f'm5_{lang}_{name}.png'))
        page.evaluate('voiceForm()');shot('voice_idle')
        box=page.locator('#voice-mic').bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down()
        page.wait_for_function("recorder && recorder.state === 'recording'");page.wait_for_timeout(700);shot('voice_holding');page.mouse.up();page.locator('#voice-preview').wait_for(state='visible');shot('voice_preview');page.evaluate('closeMedia()')
        page.evaluate('fabSheet()');page.locator('.sheet button').filter(has_text='مرفق أو صورة / كاميرا' if lang=='ar' else 'Attachment or photo / camera').click();page.wait_for_function("mediaStream && document.getElementById('camera').videoWidth > 0");shot('camera_live')
        page.evaluate('switchCamera()');page.wait_for_function("mediaStream && facing === 'user' && document.getElementById('camera').videoWidth > 0");shot('camera_front')
        page.evaluate('switchCamera()');page.wait_for_function("mediaStream && facing === 'environment' && document.getElementById('camera').videoWidth > 0")
        for i in range(3):
            page.locator('.shutter').click();page.locator('#camera-review').wait_for(state='visible')
            if i==0: shot('camera_review')
            if i<2:
                page.locator('.add-shot').click();page.wait_for_function("mediaStream && document.getElementById('camera').videoWidth > 0")
        shot('camera_multi');assert page.locator('#photo-strip button').count()==3
        page.evaluate('removePhoto()');assert page.locator('#photo-strip button').count()==2
        page.locator('#photo-caption').fill('Site caption '+lang)
        responses=[]
        def on_response(r):
            if r.url.endswith('/abroj/app/upload') and r.request.method=='POST': responses.append(r)
        page.on('response',on_response)
        page.locator('.send-photo').click();page.wait_for_function('!document.getElementById("media-modal")')
        page.wait_for_timeout(6000)
        assert len(responses)==2, len(responses)
        assert all(r.ok and r.json().get('id') for r in responses)
        assert page.evaluate('cameraCaptions') == ['Site caption '+lang] * 2
        page.remove_listener('response',on_response)
        print(lang,'two uploads passed')
        if lang=='ar':
            page.evaluate("navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error('denied'), {name:'NotAllowedError'})); openProjectCamera()")
            page.locator('.permission-sheet').wait_for();assert page.locator('.fallback-picker input').count()==1;shot('camera_fallback');page.evaluate('closeMedia()')
            page.reload();page.wait_for_function('data && data.projects.length',timeout=60000)
    browser.close()
