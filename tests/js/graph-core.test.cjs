const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../../src/sociolit/static/graph-core.js');
const node=id=>({id,title:id,current:true,tags:[],authors:[]});
const edge=(source,target,origin='tags',id='x')=>({id,source,target,origin,label:'evidence'});
test('expansion retains existing nodes, stable undirected edges and manual directions',()=>{
 const base={nodes:[node('a'),node('b')],edges:[edge('a','b'),edge('a','b','manual','ab')]};
 const before=C.clone(base),incoming={nodes:[node('b'),node('c')],edges:[edge('b','a'),edge('b','a','manual','ba'),edge('b','c')]};
 const result=C.merge(base,incoming);
 assert.deepEqual(result.added,['c']);assert.deepEqual(base,before);assert.equal(result.data.edges.length,4);
 assert.deepEqual(result.data.nodes.map(n=>n.id),['a','b','c']);
});
test('capacity never evicts existing research and refuses dangling edges',()=>{
 const base={nodes:Array.from({length:79},(_,i)=>node(String(i))),edges:[]};
 const result=C.merge(base,{nodes:[node('new'),node('overflow')],edges:[edge('0','new'),edge('new','overflow')]});
 assert.equal(result.data.nodes.length,80);assert.deepEqual(result.added,['new']);assert.equal(result.data.edges.length,1);
});
test('source filter and orphan toggle form a consistent visible subgraph',()=>{
 const graph={nodes:['a','b','c','d'].map(node),edges:[edge('a','b','manual'),edge('b','c','semantic')]};
 assert.deepEqual(C.visible(graph,'manual',false).nodes.map(n=>n.id),['a','b']);
 assert.equal(C.visible(graph,'words',false).nodes.length,0);assert.equal(C.visible(graph,'semantic',true).nodes.length,4);
});
test('force simulation separates overlap, preserves pinned anchors and stays finite for 80 nodes',()=>{
 const points=Array.from({length:80},(_,i)=>({id:String(i),x:0,y:0,vx:0,vy:0,pinned:i===0}));
 const edges=points.slice(1).map(n=>edge('0',n.id));
 for(let i=0;i<210;i++)assert.ok(Number.isFinite(C.step(points,edges)));
 assert.deepEqual({x:points[0].x,y:points[0].y},{x:0,y:0});
 assert.ok(points.slice(1).some(p=>Math.hypot(p.x,p.y)>80));
 for(const p of points){assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));assert.ok(Math.abs(p.x)<3000&&Math.abs(p.y)<3000);}
});
test('timeline is chronological, unconnected nodes have separate components',()=>{
 const graph={nodes:[{...node('a'),year:2022},{...node('b'),year:1990},node('c')],edges:[edge('a','b')]};
 const positions=C.positions(graph,'timeline');assert.ok(positions.b.x<positions.a.x);assert.ok(positions.a.x<positions.c.x);
 assert.equal(C.groups(graph).length,2);assert.deepEqual(C.positions({nodes:[],edges:[]}),{});
});

test('a newly verified missing source replaces stale current status',()=>{
 const base={nodes:[node('a')],edges:[]};
 const result=C.merge(base,{nodes:[{...node('a'),current:false}],edges:[]});
 assert.equal(result.data.nodes[0].current,false);assert.equal(base.nodes[0].current,true);
});
