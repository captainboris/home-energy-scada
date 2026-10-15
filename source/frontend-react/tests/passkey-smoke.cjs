// Actual Chromium WebAuthn with a virtual authenticator and mocked HTTP APIs.
// This does NOT verify iPhone hardware, Safari, Face ID or production deployment.
const {chromium} = require('playwright');
const {randomBytes} = require('node:crypto');
(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem('home-energy-language', 'en'));
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const {authenticatorId} = await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {
    protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true,
    isUserVerified: true, automaticPresenceSimulation: true
  }});
  let loggedIn = true, registration, assertion, registerOptions, authenticationOptions;
  const session = {ok: true, last_activity: Date.now()/1000, idle_deadline: Date.now()/1000+1800, idle_seconds: 1800};
  const fulfill = (route, body, status=200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(body)});
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/session') return fulfill(route, loggedIn ? session : {error:{code:'SESSION_TOKEN_MISSING'}}, loggedIn ? 200 : 401);
    if (path === '/api/logout') {loggedIn=false; return fulfill(route,{ok:true});}
    if (path === '/api/activity') return fulfill(route,{ok:true});
    if (path === '/api/passkey/register/options') {
      registerOptions = {challenge_id:'registration', publicKey:{challenge:randomBytes(32).toString('base64url'),
        rp:{id:'localhost',name:'Home Energy'}, user:{id:randomBytes(32).toString('base64url'),name:'Home Energy',displayName:'Home Energy'},
        pubKeyCredParams:[{type:'public-key',alg:-7}], attestation:'none',
        authenticatorSelection:{residentKey:'required',userVerification:'required',authenticatorAttachment:'platform'}}};
      return fulfill(route,registerOptions);
    }
    if (path === '/api/passkey/register/verify') {registration=route.request().postDataJSON(); return fulfill(route,{ok:true});}
    if (path === '/api/passkey/login/options') {
      authenticationOptions = {challenge_id:'authentication', publicKey:{challenge:randomBytes(32).toString('base64url'),rpId:'localhost',userVerification:'required'}};
      return fulfill(route,authenticationOptions);
    }
    if (path === '/api/passkey/login/verify') {assertion=route.request().postDataJSON(); loggedIn=true; return fulfill(route,session);}
    return fulfill(route,{data:{energy:{},series:[],latest:{},points:[],range:{start_ms:0,end_ms:1},warnings:[],availability:{},data_quality:{}}});
  });
  await page.goto('http://localhost:4173/daily.html?view=week&date=2026-10-01');
  await page.getByRole('button',{name:'EN',exact:true}).click();
  await page.locator('summary').click();
  await page.getByLabel('Administrator grant').fill('mock-operator-grant');
  await page.getByLabel('Passkey name').fill('Virtual Chromium');
  await page.getByRole('button',{name:'Prepare registration',exact:true}).click();
  await page.getByRole('button',{name:'Continue verification',exact:true}).click();
  await page.getByText('Passkey registered.',{exact:true}).waitFor();
  if (!registration?.credential?.response?.attestationObject) throw Error('No actual browser registration');
  const credentials = (await cdp.send('WebAuthn.getCredentials',{authenticatorId})).credentials;
  if (credentials.length !== 1 || !credentials[0].isResidentCredential) throw Error('Missing discoverable virtual credential');
  await page.getByRole('button',{name:'Log out',exact:true}).click();
  await page.getByRole('button',{name:'Sign in with a passkey',exact:true}).click();
  await page.getByRole('button',{name:'Continue verification',exact:true}).click();
  await page.waitForURL(url => url.pathname === '/' && url.searchParams.get('view') === 'day');
  if (!assertion?.credential?.response?.signature || assertion.credential.id !== registration.credential.id) throw Error('No actual browser assertion');
  const melbourneToday = await page.evaluate(() => window.HomeEnergyUI.todayString());
  if (new URL(page.url()).searchParams.get('date') !== melbourneToday) throw Error('Incorrect login landing');
  await page.goto('http://localhost:4173/daily.html?view=week&date=2026-10-01');
  await page.waitForSelector('header');
  if (new URL(page.url()).searchParams.get('view') !== 'week') throw Error('Authenticated deep link changed');
  if (process.env.SCADA_SMOKE_OUTPUT) {
    const fs = require('node:fs'), path = require('node:path');
    fs.mkdirSync(process.env.SCADA_SMOKE_OUTPUT,{recursive:true});
    fs.writeFileSync(path.join(process.env.SCADA_SMOKE_OUTPUT,'browser-credential.json'), JSON.stringify({registration,assertion,registerOptions,authenticationOptions}));
  }
  await browser.close();
  console.log('PASS: Chromium virtual WebAuthn registration/assertion, shared landing and deep link (mock API; NOT real hardware)');
})().catch(error => {console.error(error); process.exitCode=1;});
