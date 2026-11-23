(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $('railCanvas');
  const ctx = canvas.getContext('2d');
  const captureCanvas = document.createElement('canvas');
  const captureCtx = captureCanvas.getContext('2d');
  const video = $('railVideo');
  let stream = null, sourceReady = false, sourceMode = 'upload';
  let roi = null, dragStart = null, active = false, sending = false;
  let frameTimer = null, analysisTimer = null, serverDevice = 0, localVideoUrl = null;

  function message(text, error=false) { $('railMessage').textContent = text; $('railMessage').classList.toggle('error', error); }
  function state(text, kind='offline') { $('railState').className = `rail-state ${kind}`; $('railState').querySelector('b').textContent = text; }
  function drawPlaceholder(text='尚未載入影像') { canvas.width=0; canvas.height=0; $('railCanvasPlaceholder').textContent=text; $('railCanvasPlaceholder').hidden=false; sourceReady=false; $('railStartButton').disabled=true; }
  function showCanvas() { $('railCanvasPlaceholder').hidden=true; sourceReady=true; $('railStartButton').disabled=false; }
  function drawFrame(frame) {
    if (!frame || !frame.width || !frame.height) return;
    if (canvas.width !== frame.width || canvas.height !== frame.height) { canvas.width=frame.width; canvas.height=frame.height; }
    ctx.drawImage(frame,0,0,canvas.width,canvas.height);
    if (roi) { ctx.save(); ctx.strokeStyle='#31e0a1'; ctx.lineWidth=Math.max(2,canvas.width/500); ctx.setLineDash([8,5]); ctx.strokeRect(...roi); ctx.restore(); }
    if (dragStart) { ctx.save(); ctx.strokeStyle='#ffd166'; ctx.lineWidth=2; ctx.strokeRect(dragStart.x,dragStart.y,dragStart.w,dragStart.h); ctx.restore(); }
    showCanvas();
  }
  function canvasPoint(event) {
    const rect=canvas.getBoundingClientRect();
    return {x:Math.max(0,Math.min(canvas.width,(event.clientX-rect.left)*canvas.width/rect.width)),y:Math.max(0,Math.min(canvas.height,(event.clientY-rect.top)*canvas.height/rect.height))};
  }
  canvas.addEventListener('pointerdown',e=>{ if(!sourceReady||active)return; canvas.setPointerCapture(e.pointerId); const p=canvasPoint(e); dragStart={x:p.x,y:p.y,w:0,h:0}; });
  canvas.addEventListener('pointermove',e=>{ if(!dragStart)return; const p=canvasPoint(e); const x=Math.min(dragStart.x,p.x),y=Math.min(dragStart.y,p.y); const w=Math.abs(p.x-dragStart.x),h=Math.abs(p.y-dragStart.y); const start={...dragStart}; dragStart={x,y,w,h}; redrawPreview(); dragStart=start; });
  canvas.addEventListener('pointerup',e=>{ if(!dragStart)return; const p=canvasPoint(e),s=dragStart; roi=[Math.round(Math.min(s.x,p.x)),Math.round(Math.min(s.y,p.y)),Math.round(Math.abs(p.x-s.x)),Math.round(Math.abs(p.y-s.y))]; dragStart=null; redrawPreview(); $('railPreviewHint').textContent=`ROI：${roi.join(', ')}`; message(roi[2]>=20&&roi[3]>=20?'ROI 已選取，可以開始分析。':'ROI 太小，請重新框選至少 20 × 20 像素。'); });
  function redrawPreview(){ if(sourceMode==='server'){ if(window._railServerImage)drawFrame(window._railServerImage); } else if(video.readyState>=2){drawFrame(video);} }

  $('railSource').addEventListener('change',e=>{
    sourceMode=e.target.value; stopLocalSources(); roi=null; drawPlaceholder();
    $('railUploadControls').hidden=sourceMode!=='upload'; $('railBrowserControls').hidden=sourceMode!=='browser'; $('railServerControls').hidden=sourceMode!=='server';
    $('railPreviewHint').textContent='請載入影像並框選鐵軌 ROI';
  });
  function stopLocalSources(){ if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;} video.pause(); video.srcObject=null; if(localVideoUrl){URL.revokeObjectURL(localVideoUrl);localVideoUrl=null;} }
  $('railVideoFile').addEventListener('change',e=>{
    stopLocalSources(); const file=e.target.files[0]; if(!file)return;
    const allowed=['video/mp4','video/webm','video/quicktime','video/ogg','']; if(!allowed.includes(file.type)){message('不支援的影片格式，請使用 MP4、WebM、MOV 或 OGG。',true);return;}
    localVideoUrl=URL.createObjectURL(file); video.src=localVideoUrl; video.loop=true; video.onloadedmetadata=()=>{ $('railFps').value=Math.min(120,Math.max(1,Math.round(video.getVideoPlaybackQuality?.().totalVideoFrames/video.duration)||30)); video.currentTime=0; video.play().then(()=>{sourceReady=true;drawFrame(video);message('影片已載入。請在預覽畫面拖曳框選鐵軌 ROI。');}).catch(()=>message('瀏覽器無法播放此影片。',true));};
    video.ontimeupdate=()=>{if(!active)redrawPreview();};
  });
  $('railCameraButton').addEventListener('click',async()=>{
    try{stopLocalSources();stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:false});video.srcObject=stream;await video.play();drawFrame(video);message('攝影機已開啟。請拖曳框選鐵軌 ROI。');}catch(err){message(`無法開啟瀏覽器攝影機：${err.message}`,true);}
  });
  $('railServerPreviewButton').addEventListener('click',async()=>{
    try{serverDevice=Number($('railDeviceIndex').value||0);const r=await fetch(`/api/rail/server-camera/preview?device_index=${serverDevice}`,{cache:'no-store'});if(!r.ok){const d=await r.json();throw new Error(d.error||'攝影機預覽失敗');}const blob=await r.blob();const img=new Image();img.onload=()=>{window._railServerImage=img;roi=null;drawFrame(img);message('伺服器攝影機預覽已載入。請框選鐵軌 ROI。');};img.src=URL.createObjectURL(blob);}catch(err){message(err.message,true);}
  });

  async function postForm(url,form){const r=await fetch(url,{method:'POST',body:form});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'請求失敗');return d;}
  function currentFrameBlob(){const frame=sourceMode==='server'?window._railServerImage:video;if(!frame||!frame.videoWidth&&!frame.naturalWidth)throw new Error('目前沒有可擷取的影格');const w=frame.videoWidth||frame.naturalWidth,h=frame.videoHeight||frame.naturalHeight;captureCanvas.width=w;captureCanvas.height=h;captureCtx.drawImage(frame,0,0,w,h);return new Promise((resolve,reject)=>captureCanvas.toBlob(b=>b?resolve(b):reject(new Error('影格轉換失敗')),'image/jpeg',.86));}
  async function initializeEngine(){
    if(!sourceReady||!roi||roi[2]<20||roi[3]<20)throw new Error('請先載入影像並選取有效 ROI。');
    const blob=await currentFrameBlob();const form=new FormData();form.append('frame',blob,'frame.jpg');form.append('roi',roi.join(','));form.append('fps',$('railFps').value||30);form.append('direction',$('railDirection').value);form.append('source',sourceMode);
    await postForm('/api/rail/initialize',form);
  }
  async function sendFrame(){
    if(sending||!active)return;sending=true;
    try{redrawPreview();const blob=await currentFrameBlob();const form=new FormData();form.append('frame',blob,'frame.jpg');form.append('timestamp',(performance.now()/1000).toString());const d=await postForm('/api/rail/frame',form);renderFrameResult(d.result);}
    catch(err){message(err.message,true);}finally{sending=false;}
  }
  function renderFrameResult(r){$('railTrackStatus').textContent=r.status||'--';$('railConfidence').textContent=(Number(r.confidence||0)*100).toFixed(1)+'%';$('railShakeStatus').textContent=r.shake_compensation?'啟用':'未啟用';$('railBlurStatus').textContent=r.is_blurry?'是':'否';$('railSampleCount').textContent=$('railSampleCount').textContent==='0'?'1':$('railSampleCount').textContent;}
  $('railStartButton').addEventListener('click',async()=>{
    try{
      if(sourceMode==='server'){ if(!window._railServerImage)throw new Error('請先取得伺服器攝影機預覽。'); }
      await initializeEngine();active=true;state('分析中','online');$('railStartButton').disabled=true;$('railStopButton').disabled=false;$('railAnalyzeButton').disabled=false;$('railRecordBaseline').disabled=false;$('railBuildBaseline').disabled=false;
      if(sourceMode==='server'){
        const r=await fetch('/api/rail/server-camera/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_index:serverDevice})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'伺服器攝影機啟動失敗');
      }else{
        if(sourceMode==='upload'){video.currentTime=0;await video.play();}
        frameTimer=window.setInterval(sendFrame,Math.max(50,1000/Math.min(60,Number($('railFps').value)||30)));
      }
      analysisTimer=window.setInterval(loadAnalysis,2500);message('Rail 分析已啟動。累積足夠影格後即可查看 FFT 結果。');
    }catch(err){active=false;state('啟動失敗','error');message(err.message,true);}
  });
  async function loadAnalysis(){try{const r=await fetch(`/api/rail/analyze?direction=${encodeURIComponent($('railDirection').value)}`,{cache:'no-store'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'分析尚未就緒');renderAnalysis(d.analysis);}catch(err){message(err.message);}}
  function fmt(v,n=3){return Number.isFinite(Number(v))?Number(v).toFixed(n):'--';}
  function renderAnalysis(a){$('railFrequency').innerHTML=`${fmt(a.frequency,3)}<small>Hz</small>`;$('railAmplitude').innerHTML=`${fmt(a.amplitude,3)}<small>px</small>`;$('railPhase').innerHTML=`${fmt(a.phase,2)}<small>°</small>`;$('railRms').innerHTML=`${fmt(a.rms,3)}<small>px</small>`;$('railSampleRate').textContent=fmt(a.sample_rate_hz,2)+' Hz';$('railSnr').textContent=a.snr_db==null?'--':fmt(a.snr_db,2)+' dB';$('railSampleCount').textContent=a.sample_count??0;$('railTrackStatus').textContent='分析完成';
    const status=a.baseline_status||'insufficient_data';const baseline=$('railBaselineStatus');baseline.className='rail-baseline-status '+(status==='normal'?'normal':status==='abnormal'?'abnormal':'');baseline.textContent=status==='normal'?'正常：主頻率位於基準範圍內':status==='abnormal'?'異常：主頻率超出正常基準範圍':status==='insufficient_data'?'尚無足夠正常樣本，無法判定是否異常':'無有效頻率資料';
    const peaks=a.top_peaks||[];$('railTopPeaks').innerHTML=peaks.length?'<b>Top 頻率峰值：</b>'+peaks.map((p,i)=>`${i+1}. ${fmt(p.frequency,3)} Hz / ${fmt(p.amplitude,3)} px`).join('　'):'尚無頻率峰值資料';
  }
  $('railAnalyzeButton').addEventListener('click',loadAnalysis);
  $('railStopButton').addEventListener('click',stopAnalysis);
  async function stopAnalysis(){active=false;if(frameTimer)clearInterval(frameTimer);if(analysisTimer)clearInterval(analysisTimer);frameTimer=analysisTimer=null;try{await fetch('/api/rail/stop',{method:'POST'});}catch(_){}stopLocalSources();state('已停止','offline');$('railStartButton').disabled=!sourceReady;$('railStopButton').disabled=true;$('railAnalyzeButton').disabled=true;$('railRecordBaseline').disabled=true;$('railBuildBaseline').disabled=true;message('分析已停止。');}
  $('railClearButton').addEventListener('click',()=>{roi=null;redrawPreview();$('railPreviewHint').textContent='尚未選取 ROI';message('ROI 已清除，請重新框選。');});
  $('railRecordBaseline').addEventListener('click',async()=>{try{const r=await fetch('/api/rail/baseline/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:$('railBaselineLabel').value})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'記錄失敗');message('正常振動樣本已記錄。');}catch(e){message(e.message,true);}});
  $('railBuildBaseline').addEventListener('click',async()=>{try{const r=await fetch('/api/rail/baseline/build',{method:'POST'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'建立基準失敗');message(`基準更新完成，共 ${d.baselines.length} 個標籤。`);await loadAnalysis();}catch(e){message(e.message,true);}});
  window.addEventListener('beforeunload',()=>{if(active)navigator.sendBeacon('/api/rail/stop');stopLocalSources();});
  fetch('/api/rail/status').then(r=>r.json()).then(d=>{if(d.active){state('已有分析工作階段','online');$('railTrackStatus').textContent=d.initialized?'已初始化':'未初始化';$('railRoiStatus').textContent=d.roi?d.roi.join(', '):'--';}}).catch(()=>{});
  drawPlaceholder();
})();
