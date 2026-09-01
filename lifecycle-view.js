(() => {
  const L = window.LG_LIFECYCLE;
  const CORE = L?.meta?.core_lobs || ['iPhone','Mac','iPad','Watch','AirPods'];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => new Intl.NumberFormat('en-IN',{maximumFractionDigits:0}).format(value || 0);
  const money = value => value >= 1e7 ? `₹${(value/1e7).toFixed(1)} Cr` : `₹${num(value)}`;
  const bitCount = value => { let n=value||0,c=0; while(n){c+=n&1;n>>=1} return c };
  const maskNames = mask => CORE.filter((_,i)=>mask&(1<<i));
  const rows = source => (source||[]).map(r=>({channel:r[0],store:r[1],year:r[2],first:r[3],mask:r[4],customers:r[5],repeat:r[6],value:r[7],firstMin:r[8],lastMax:r[9]}));
  const national = rows(L?.national_rows), stores = rows(L?.store_rows);
  let ready = false;

  function option(values,label){return `<option value="all">All ${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}
  function rebuildStores(){
    const channel=document.getElementById('lcChannel').value, select=document.getElementById('lcStore'), current=select.value;
    const values=[...new Set(stores.filter(r=>channel==='all'||r.channel===channel).map(r=>r.store))].sort();
    select.innerHTML=option(values,'stores / selling points'); if(values.includes(current))select.value=current;
  }
  function selectedRows(){
    const channel=document.getElementById('lcChannel').value,store=document.getElementById('lcStore').value,year=document.getElementById('lcYear').value,first=document.getElementById('lcFirst').value;
    const source=store==='all'?national:stores;
    return source.filter(r=>(channel==='all'||r.channel===channel)&&(store==='all'||r.store===store)&&(year==='all'||r.year===Number(year))&&(first==='all'||r.first===first));
  }
  function render(){
    if(!L)return;
    const data=selectedRows(), total=data.reduce((s,r)=>s+r.customers,0), repeat=data.reduce((s,r)=>s+r.repeat,0), value=data.reduce((s,r)=>s+r.value,0);
    const multi=data.reduce((s,r)=>s+(bitCount(r.mask)>=2?r.customers:0),0), earliest=data.reduce((m,r)=>!m||r.firstMin<m?r.firstMin:m,''), latest=data.reduce((m,r)=>r.lastMax>m?r.lastMax:m,'');
    const bought=CORE.map((lob,i)=>[lob,data.reduce((s,r)=>s+((r.mask&(1<<i))?r.customers:0),0)]), gaps=bought.map(([lob,count])=>[lob,total-count]).sort((a,b)=>b[1]-a[1]);
    const firstGroups=[...new Set(data.map(r=>r.first))], topFirst=firstGroups.map(name=>[name,data.filter(r=>r.first===name).reduce((s,r)=>s+r.customers,0)]).sort((a,b)=>b[1]-a[1])[0]||['No observed cohort',0];
    const opportunity=gaps[0]||['No gap',0], expansion=total?multi/total:0, repeatRate=total?repeat/total:0;
    const selectedStore=document.getElementById('lcStore').value, scope=selectedStore==='all'?'selected channel scope':selectedStore;
    document.getElementById('lcKpis').innerHTML=total?`<div class="kpi"><span>Lifecycle customers</span><b>${num(total)}</b><small>Privacy-safe cohort total</small></div><div class="kpi"><span>Repeat relationship</span><b>${(repeatRate*100).toFixed(1)}%</b><small>${num(repeat)} customers with 2+ invoices</small></div><div class="kpi"><span>Multi-LOB penetration</span><b>${(expansion*100).toFixed(1)}%</b><small>${num(multi)} customers reached 2+ LOBs</small></div><div class="kpi"><span>Observed customer value</span><b>${money(value)}</b><small>Net linked value</small></div><div class="kpi"><span>Largest first-purchase entry</span><b>${esc(topFirst[0])}</b><small>${num(topFirst[1])} customers</small></div><div class="kpi"><span>Largest next-LOB pool</span><b>${esc(opportunity[0])}</b><small>${num(opportunity[1])} have no visible purchase</small></div>`:'<div class="lgError">No privacy-safe lifecycle cohort matches this selection. Reset one or more filters.</div>';
    document.getElementById('lcFinding').innerHTML=total?`<b>Lifecycle read:</b> In ${esc(scope)}, <b>${(expansion*100).toFixed(1)}%</b> of the selected cohort has expanded beyond one core LOB. The largest remaining ecosystem opportunity is <b>${esc(opportunity[0])}</b>, absent from the observed history of <b>${num(opportunity[1])} customers</b>. This is an opportunity pool, not proof that every customer needs the product.`:'Select another scope to view lifecycle intelligence.';
    document.getElementById('lcJourney').innerHTML=total?`<div class="lcStage"><div class="eyebrow">1 · Relationship entry</div><h3>${esc(topFirst[0])}</h3><p>The most common first observed core-product entry in this filtered cohort. First purchase dates span ${esc(earliest)} onward.</p></div><div class="lcStage"><div class="eyebrow">2 · Bought through latest history</div><h3>${num(multi)} multi-LOB customers</h3><p>Categories marked green have an observed positive sale by ${esc(latest)}.</p><div class="lcNodes">${bought.map(([lob,count])=>`<span class="lcNode have">${lob}: ${num(count)}</span>`).join('')}</div></div><div class="lcStage"><div class="eyebrow">3 · Not yet visible / next conversation</div><h3>${esc(opportunity[0])} opportunity</h3><p>Missing means no positive purchase is visible under the same Customer Code in the available history; it does not prove the customer does not own the category elsewhere.</p><div class="lcNodes">${gaps.map(([lob,count])=>`<span class="lcNode gap">${lob}: ${num(count)}</span>`).join('')}</div></div>`:'';
    const paths=[...data].sort((a,b)=>b.customers-a.customers).slice(0,25);
    document.getElementById('lcPaths').innerHTML=`<div class="lcPath head"><span>First observed LOB</span><span>Bought by latest history</span><span>Not yet visible</span><span>Customers</span><span>Repeat</span><span>Value</span></div>`+paths.map(r=>{const have=maskNames(r.mask),missing=CORE.filter(x=>!have.includes(x));return`<div class="lcPath"><strong>${esc(r.first)}</strong><span>${esc(have.join(' + ')||'None')}</span><span>${esc(missing.join(' + ')||'Complete core ecosystem')}</span><span>${num(r.customers)}</span><span>${(r.customers?r.repeat/r.customers*100:0).toFixed(1)}%</span><span>${money(r.value)}</span></div>`}).join('');
    document.getElementById('lcStatus').innerHTML=`${num(data.length)} published cohort rows · source coverage ${L.meta.coverage_start} to ${L.meta.coverage_end} · cells below ${L.meta.minimum_customer_threshold} customers are aggregated or suppressed.`;
  }
  window.initLifecycle=()=>{
    if(!L){document.getElementById('lifecycle').innerHTML='<div class="lgError">Lifecycle aggregate data is unavailable.</div>';return}
    if(!ready){
      const channels=[...new Set(national.map(r=>r.channel))].sort(), years=[...new Set(national.map(r=>r.year))].sort(), first=[...new Set(national.map(r=>r.first))].sort();
      document.getElementById('lcChannel').innerHTML=option(channels,'channels'); document.getElementById('lcYear').innerHTML=option(years,'first-purchase years'); document.getElementById('lcFirst').innerHTML=option(first,'first observed LOBs'); rebuildStores();
      document.getElementById('lcChannel').onchange=()=>{rebuildStores();render()}; ['lcStore','lcYear','lcFirst'].forEach(id=>document.getElementById(id).onchange=render); document.getElementById('lcReset').onclick=()=>{['lcChannel','lcStore','lcYear','lcFirst'].forEach(id=>document.getElementById(id).value='all');rebuildStores();render()}; ready=true;
    }
    render();
  };
})();
