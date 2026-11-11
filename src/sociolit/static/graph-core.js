/* Pure graph operations shared by the renderer and deterministic offline tests. */
(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;else root.GraphCore=value;})(globalThis,()=>{
  const MAX_NODES=80,MAX_EDGES=1800;
  const clone=value=>JSON.parse(JSON.stringify(value));
  function edgeKey(edge){
    if(edge.origin==='manual')return 'manual:'+edge.id;
    return JSON.stringify([edge.origin,...[edge.source,edge.target].sort(),edge.origin==='comparison'?edge.label:'']);
  }
  function merge(base,incoming){
    const nodes=new Map((base?.nodes||[]).map(n=>[n.id,clone(n)])),added=[];
    for(const node of incoming.nodes){
      if(nodes.has(node.id)){nodes.set(node.id,clone(node));}
      else if(nodes.size<MAX_NODES){nodes.set(node.id,clone(node));added.push(node.id);}
    }
    const edges=new Map();
    for(const edge of [...(base?.edges||[]),...incoming.edges])if(nodes.has(edge.source)&&nodes.has(edge.target))edges.set(edgeKey(edge),clone(edge));
    const ordered=[...edges.values()].sort((a,b)=>(a.origin==='manual'?0:1)-(b.origin==='manual'?0:1));
    return {data:{...clone(incoming),nodes:[...nodes.values()],edges:ordered.slice(0,MAX_EDGES),edges_limited:ordered.length>MAX_EDGES||!!base?.edges_limited},added,edgesLimited:ordered.length>MAX_EDGES};
  }
  function visible(data,origin='all',orphans=true){
    const groups={manual:['manual'],words:['metadata','tags','title'],semantic:['semantic'],comparison:['comparison']};
    const edges=data.edges.filter(e=>origin==='all'||groups[origin]?.includes(e.origin));
    const ids=new Set(edges.flatMap(e=>[e.source,e.target]));
    return {nodes:data.nodes.filter(n=>orphans||ids.has(n.id)),edges};
  }
  function groups(data){
    const neighbors=new Map(data.nodes.map(n=>[n.id,new Set()]));
    for(const e of data.edges){neighbors.get(e.source)?.add(e.target);neighbors.get(e.target)?.add(e.source);}
    const seen=new Set(),result=[];
    for(const n of data.nodes){if(seen.has(n.id))continue;const group=[],queue=[n.id];seen.add(n.id);
      for(let i=0;i<queue.length;i++){const id=queue[i];group.push(id);for(const other of neighbors.get(id)||[])if(!seen.has(other)){seen.add(other);queue.push(other);}}
      result.push(group);
    }
    return result.sort((a,b)=>b.length-a.length||a[0].localeCompare(b[0]));
  }
  function positions(data,mode='network',seed=''){
    const result={},degree=new Map(data.nodes.map(n=>[n.id,0]));
    for(const e of data.edges){degree.set(e.source,(degree.get(e.source)||0)+1);degree.set(e.target,(degree.get(e.target)||0)+1);}
    if(mode==='timeline'){
      const years=new Map();for(const node of data.nodes){const year=String(node.year||'未注明').match(/\d{4}/)?.[0]||'未注明';if(!years.has(year))years.set(year,[]);years.get(year).push(node.id);}
      [...years.keys()].sort().forEach((year,i)=>years.get(year).forEach((id,j)=>{result[id]={x:i*210,y:j*125};}));
    }else if(mode==='concentric'){
      const center=data.nodes.find(n=>n.id===seed)||[...data.nodes].sort((a,b)=>degree.get(b.id)-degree.get(a.id))[0];
      if(!center)return result;result[center.id]={x:0,y:0};
      const others=data.nodes.filter(n=>n.id!==center.id),r=Math.max(160,others.length*26);
      others.forEach((n,i)=>{const a=2*Math.PI*i/others.length;result[n.id]={x:r*Math.cos(a),y:r*Math.sin(a)};});
    }else{
      const components=groups(data),connected=components.filter(g=>g.length>1),orphans=components.filter(g=>g.length===1).flat();
      connected.forEach((ids,index)=>{
        const ox=(index%2)*460,oy=Math.floor(index/2)*410;
        const sorted=ids.slice().sort((a,b)=>degree.get(b)-degree.get(a)||a.localeCompare(b));
        result[sorted[0]]={x:ox,y:oy};const r=Math.max(125,Math.min(265,sorted.length*22));
        sorted.slice(1).forEach((id,i)=>{const a=2*Math.PI*i/Math.max(1,sorted.length-1);result[id]={x:ox+r*Math.cos(a),y:oy+r*Math.sin(a)};});
      });
      const columns=Math.min(6,Math.max(3,Math.ceil(Math.sqrt(orphans.length))));
      const top=connected.length?Math.ceil(connected.length/2)*410:0;
      orphans.forEach((id,i)=>{result[id]={x:(i%columns)*135-80,y:top+Math.floor(i/columns)*115};});

    }
    return result;
  }
  function step(points,edges,center={x:0,y:0},strength=1){
    const force=points.map(p=>({x:(center.x-p.x)*.0006,y:(center.y-p.y)*.0006})),index=new Map(points.map((p,i)=>[p.id,i]));
    for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
      let dx=points[j].x-points[i].x,dy=points[j].y-points[i].y;
      if(Math.abs(dx)+Math.abs(dy)<.01){dx=(i+1)*.31;dy=(j+1)*.19;}
      const d=Math.max(5,Math.hypot(dx,dy)),magnitude=Math.min(8,6500*strength/(d*d)+(d<105?(105-d)*.025:0));
      const x=dx/d*magnitude,y=dy/d*magnitude;force[i].x-=x;force[i].y-=y;force[j].x+=x;force[j].y+=y;
    }
    const pairs=new Set();for(const edge of edges){const a=index.get(edge.source),b=index.get(edge.target);if(a===undefined||b===undefined)continue;
      const key=[a,b].sort((x,y)=>x-y).join(':');if(pairs.has(key))continue;pairs.add(key);
      const dx=points[b].x-points[a].x,dy=points[b].y-points[a].y,d=Math.max(1,Math.hypot(dx,dy)),k=(d-155)*.006;
      force[a].x+=dx/d*k;force[a].y+=dy/d*k;force[b].x-=dx/d*k;force[b].y-=dy/d*k;
    }
    let energy=0;
    points.forEach((p,i)=>{
      if(p.pinned){p.vx=p.vy=0;return;}
      p.vx=Math.max(-9,Math.min(9,((p.vx||0)+force[i].x)*.78));p.vy=Math.max(-9,Math.min(9,((p.vy||0)+force[i].y)*.78));
      p.x+=p.vx;p.y+=p.vy;energy+=p.vx*p.vx+p.vy*p.vy;
    });return energy/Math.max(1,points.length);
  }
  function timelineLabel(node){return String(node.year||'').match(/\d{4}/)?.[0]||'未注明';}
  return {MAX_NODES,MAX_EDGES,clone,edgeKey,merge,visible,groups,positions,step,timelineLabel};
});
