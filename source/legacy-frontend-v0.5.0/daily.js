"use strict";
const UI=window.HomeEnergyUI;
const {$,t,stampLabel,analyticsTimeLabel,localInput,displayDateTime,periodFromUrl,periodQuery,writePeriodUrl,PeriodNavigator,api,writeStorage,socState}=UI;
const IDLE_MS=UI.IDLE_MS,ACTIVITY_KEY=UI.ACTIVITY_KEY,LOGOUT_KEY=UI.LOGOUT_KEY;
const controllers=new Set();
let data=null,active=false,busy=false,generation=0,refreshTimer=null,idleTimer=null,activityTimer=null;
let lastHuman=0,lastActivitySent=0,lastStorageWrite=0,activityBusy=false;
let selectedPeriod=periodFromUrl(),selected=periodQuery(selectedPeriod);

const energyCards=[
  ["energy.pv","pv_kwh"],["energy.load","load_kwh"],
  ["energy.import","grid_import_kwh"],["energy.export","grid_export_kwh"],
  ["energy.charge","battery_charge_kwh"],["energy.discharge","battery_discharge_kwh"]
];

async function request(path,options={}){return api(path,controllers,options);}
function setAuthView(view,message=""){$("auth-loading").hidden=view!=="loading";$("login").hidden=view!=="login";$("dashboard").hidden=view!=="app";if(view==="loading"&&message)$("auth-loading").querySelector("div").textContent=message;if(view==="login"){$("login-error").textContent=message;$("password").value="";}}
function showLogin(message=""){generation++;active=false;busy=false;activityBusy=false;clearTimeout(refreshTimer);clearTimeout(activityTimer);clearInterval(idleTimer);refreshTimer=activityTimer=idleTimer=null;for(const controller of controllers)controller.abort();controllers.clear();setAuthView("login",message);$("mode").hidden=true;$("logout").hidden=true;$("refresh").disabled=false;data=null;}
function showAuthError(message){setAuthView("loading",message);$("auth-loading").querySelector(".spinner").hidden=true;}
function startSession(session){active=true;generation++;lastHuman=session.last_activity*1000;$("auth-loading").querySelector(".spinner").hidden=false;setAuthView("app");$("mode").hidden=false;$("logout").hidden=false;idleTimer=setInterval(checkIdle,1000);renderLoading();refresh(true,true);}
async function logout(message="",broadcast=true){showLogin(message);if(broadcast)writeStorage(LOGOUT_KEY,Date.now());try{await request("/api/logout",{method:"POST",body:"{}"});}catch{}}
function checkIdle(){if(!active)return true;if(Date.now()-lastHuman>=IDLE_MS){logout(t("auth.idle"));return true;}return false;}
function humanActivity(event){if(!active||!event.isTrusted)return;if(checkIdle())return;lastHuman=Date.now();if(lastHuman-lastStorageWrite>1000){writeStorage(ACTIVITY_KEY,lastHuman);lastStorageWrite=lastHuman;}if(!activityTimer&&!activityBusy)activityTimer=setTimeout(sendActivity,Math.max(0,30000-(Date.now()-lastActivitySent)));}
async function sendActivity(){activityTimer=null;if(!active||activityBusy||checkIdle())return;const idle=(Date.now()-lastHuman)/1000;if(idle>60)return;activityBusy=true;lastActivitySent=Date.now();const ticket=generation;try{await request("/api/activity",{method:"POST",body:JSON.stringify({idle_seconds:Math.max(0,idle)})});}catch(error){if(ticket===generation&&error.status===401)showLogin(error.message);}finally{if(ticket===generation)activityBusy=false;}}
function scheduleRefresh(){clearTimeout(refreshTimer);if(active&&!document.hidden)refreshTimer=setTimeout(()=>refresh(false,false),60000);$("refresh-state").textContent=t(document.hidden?"status.paused":"status.auto");}
function fmt(value,digits=2){return typeof value==="number"&&Number.isFinite(value)?value.toFixed(digits):"—";}
function rangeText(){if(selectedPeriod.mode==="other")return `${displayDateTime(selectedPeriod.fromDate,selectedPeriod.fromTime)} — ${displayDateTime(selectedPeriod.toDate,selectedPeriod.toTime)} · ${t("range.melbourne")}`;const finish=localInput(selectedPeriod.endMs-1).date;return `${displayDateTime(selectedPeriod.fromDate,"00:00")} — ${displayDateTime(finish,"23:59")} · ${t("range.melbourne")}`;}

function makeCard({label,description,value="—",unit="",meta="",status=null,loading=false,accent=false,progress=null}){
  const node=document.createElement("article");node.className="card kpi-card"+(accent?" accent":"");node.setAttribute("aria-busy",String(loading));
  const copy=document.createElement("div");copy.className="kpi-copy";const title=document.createElement("div");title.className="label";title.textContent=label;const detail=document.createElement("div");detail.className="detail";detail.textContent=description;copy.append(title,detail);
  const reading=document.createElement("div");reading.className="kpi-reading";
  if(loading){const valueSkeleton=document.createElement("span"),metaSkeleton=document.createElement("span");valueSkeleton.className="skeleton skeleton-value";metaSkeleton.className="skeleton skeleton-meta";reading.append(valueSkeleton,metaSkeleton);}else{const amount=document.createElement("div");amount.className="value value-reveal"+(status?` ${status.className}`:"");amount.textContent=value;if(unit){const suffix=document.createElement("span");suffix.className="unit";suffix.textContent=unit;amount.append(suffix);}reading.append(amount);if(meta){const note=document.createElement("div");note.className="kpi-meta value-reveal";note.textContent=meta;reading.append(note);}if(status){const state=document.createElement("div");state.className=`kpi-status ${status.className}`;state.textContent=status.label;reading.append(state);}}
  if(progress!==null){const bar=document.createElement("div");bar.className="coverage";const fill=document.createElement("span");fill.style.width=Math.max(0,Math.min(100,progress))+"%";bar.append(fill);reading.append(bar);}
  node.append(copy,reading);return node;
}

function renderLoading(){
  $("range-label").textContent=rangeText();$("read-time").textContent="";$("banner").hidden=true;
  $("energy").replaceChildren(...energyCards.map(([label])=>makeCard({label:t(label),description:t("energy.rangeDetail"),loading:true})));
  $("performance").replaceChildren(makeCard({label:t("performance.self"),description:t("performance.formula"),loading:true,accent:true}));
  $("peaks").replaceChildren(...["peak.pv","peak.import","peak.export"].map(label=>makeCard({label:t(label),description:t("peak.detail"),loading:true})));
  $("battery").replaceChildren(
    makeCard({label:t("battery.reserve"),description:t("battery.reserveDetail",{value:"—"}),loading:true}),
    makeCard({label:t("battery.minimum"),description:t("battery.minimumDetail"),loading:true}),
    makeCard({label:t("battery.peakPeriod"),description:t("battery.peakDetail"),loading:true})
  );
  $("quality").replaceChildren(makeCard({label:t("quality.coverage"),description:t("quality.samples",{observed:"—",expected:"—"}),loading:true}));
}

function energyCard(label,metric,energy,availability){
  const batteryMetric=metric==="battery_charge_kwh"||metric==="battery_discharge_kwh",notApplicable=batteryMetric&&!availability.battery_applicable;
  return makeCard({label:t(label),description:t("energy.rangeDetail"),value:notApplicable?t("common.notApplicable"):fmt(energy[metric]),unit:notApplicable?"":"kWh",meta:notApplicable?t("battery.notInstalled"):""});
}

function render(manual){
  if(!data)return;const energy=data.energy||{},availability=data.availability||{};
  $("energy").replaceChildren(...energyCards.map(([label,metric])=>energyCard(label,metric,energy,availability)));
  $("performance").replaceChildren(makeCard({label:t("performance.self"),description:t("performance.formula"),value:fmt(data.performance?.self_sufficiency_pct,1),unit:"%",accent:true}));
  const peaks=data.peaks||{};$("peaks").replaceChildren(
    makeCard({label:t("peak.pv"),description:t("peak.detail"),value:fmt(peaks.pv?.kw),unit:"kW",meta:analyticsTimeLabel(peaks.pv?.time,selectedPeriod)}),
    makeCard({label:t("peak.import"),description:t("peak.detail"),value:fmt(peaks.grid_import?.kw),unit:"kW",meta:analyticsTimeLabel(peaks.grid_import?.time,selectedPeriod)}),
    makeCard({label:t("peak.export"),description:t("peak.detail"),value:fmt(peaks.grid_export?.kw),unit:"kW",meta:analyticsTimeLabel(peaks.grid_export?.time,selectedPeriod)})
  );
  const battery=data.battery||{},batteryAvailable=availability.battery_applicable!==false&&battery.applicable!==false;
  const reserveValue=!batteryAvailable?t("common.notApplicable"):(battery.reserve_reached_time?analyticsTimeLabel(battery.reserve_reached_time,selectedPeriod):t("battery.notReached"));
  const reserveMeta=!batteryAvailable?t("battery.notInstalled"):(battery.reserve_reached_time?`${fmt(battery.reserve_soc_pct,0)}%`:"");
  const minimumState=batteryAvailable?socState(battery.minimum_soc_pct):null;
  $("battery").replaceChildren(
    makeCard({label:t("battery.reserve"),description:t("battery.reserveDetail",{value:batteryAvailable?fmt(battery.reserve_soc_pct,0):"—"}),value:reserveValue,meta:reserveMeta}),
    makeCard({label:t("battery.minimum"),description:t("battery.minimumDetail"),value:batteryAvailable?fmt(battery.minimum_soc_pct,0):t("common.notApplicable"),unit:batteryAvailable&&battery.minimum_soc_pct!==null&&battery.minimum_soc_pct!==undefined?"%":"",meta:!batteryAvailable?t("battery.notInstalled"):analyticsTimeLabel(battery.minimum_soc_time,selectedPeriod),status:minimumState}),
    makeCard({label:t("battery.peakPeriod"),description:t("battery.peakDetail"),value:fmt(data.peak_period?.grid_import_18_21_kwh),unit:"kWh"})
  );
  const quality=data.data_quality||{},pct=typeof quality.raw_coverage_pct==="number"?quality.raw_coverage_pct:null;
  $("quality").replaceChildren(makeCard({label:t("quality.coverage"),description:t("quality.samples",{observed:quality.raw_samples??0,expected:quality.expected_samples??0}),value:fmt(pct,1),unit:pct===null?"":"%",progress:pct}));
  let warnings=Array.isArray(data.warnings)?data.warnings:[];if(Array.isArray(data.warning_codes)&&data.warning_codes.length)warnings=data.warning_codes.map(item=>item.code==="OFFICIAL_REPORT_MISSING"?t("warning.officialMissing"):item.code==="SUMMARY_MISSING"?t("warning.summaryMissing",{days:(item.days||[]).join(", ")}):item.code);$("banner").textContent=warnings.join("\n");$("banner").hidden=!warnings.length;$("range-label").textContent=rangeText();$("read-time").textContent=t("status.readAt",{time:stampLabel(data.checked_at,true)});$("status").textContent=manual?t("status.reloadedAnalytics"):t("status.checkedAnalytics");
}

async function refresh(manual=false,newRange=false){
  if(!active||checkIdle()||busy)return;busy=true;clearTimeout(refreshTimer);if(newRange||!data)renderLoading();else $("dashboard").classList.add("is-refreshing");$("refresh").disabled=true;$("refresh").textContent=t("common.loading");$("status").textContent=t("status.readingAnalytics");const ticket=generation,params=new URLSearchParams(selected);
  try{const result=(await request("/api/summary/range?"+params)).data;if(ticket!==generation||!active)return;data=result;render(manual);}
  catch(error){if(ticket!==generation)return;if(error.status===401){showLogin(error.message);return;}$("banner").hidden=false;$("banner").textContent=error.name==="AbortError"?t("status.timeout"):error.message;$("status").textContent=t("status.failed");}
  finally{if(ticket===generation){busy=false;$("dashboard").classList.remove("is-refreshing");$("refresh").disabled=false;$("refresh").textContent=t("common.refresh");scheduleRefresh();}}
}
function updateNavLink(){$("overview-link").href="/"+location.search;}
function changePeriod(period){generation++;for(const controller of controllers)controller.abort();controllers.clear();busy=false;activityBusy=false;selectedPeriod=period;selected=periodQuery(period);data=null;updateNavLink();renderLoading();if(active)refresh(true,true);}

selectedPeriod.label=UI.periodLabel(selectedPeriod);writePeriodUrl(selectedPeriod,true);updateNavLink();
const periodNavigator=new PeriodNavigator(selectedPeriod,changePeriod);
$("login-form").addEventListener("submit",async event=>{event.preventDefault();$("login-button").disabled=true;$("login-error").textContent="";try{const session=await request("/api/login",{method:"POST",body:JSON.stringify({password:$("password").value})});$("password").value="";writeStorage(ACTIVITY_KEY,session.last_activity*1000);startSession(session);}catch(error){$("login-error").textContent=error.message;}finally{$("login-button").disabled=false;}});
$("refresh").onclick=()=>refresh(true,false);$("logout").onclick=()=>logout();
for(const name of ["pointerdown","pointermove","keydown","wheel","touchstart"])document.addEventListener(name,humanActivity,{passive:true});
window.addEventListener("storage",event=>{if(!active)return;if(event.key===LOGOUT_KEY){showLogin(t("auth.otherTab"));return;}if(event.key===ACTIVITY_KEY){const stamp=Number(event.newValue);if(stamp<=Date.now()+1000)lastHuman=Math.max(lastHuman,stamp);}});
window.addEventListener("popstate",()=>{const period=periodFromUrl();periodNavigator.setCurrent(period);changePeriod(period);});
document.addEventListener("visibilitychange",()=>{if(!active)return;if(checkIdle())return;if(document.hidden){clearTimeout(refreshTimer);clearTimeout(activityTimer);activityTimer=null;sendActivity();scheduleRefresh();}else refresh(false,false);});
window.addEventListener("pageshow",()=>{if(active&&!checkIdle())refresh(false,false);});
window.addEventListener("languagechange",()=>{updateNavLink();if(data)render(false);else renderLoading();scheduleRefresh();});
(async()=>{try{startSession(await request("/api/session"));}catch(error){if(error.status===401)showLogin("");else showAuthError(error.message);}})();
