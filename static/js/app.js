
/* SmartBill shared interactions — accessible, lightweight, no framework dependency. */
document.addEventListener('DOMContentLoaded',()=>{
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('.dashboard-heading,.metric-card,.workspace-card,.product-card,.tip-card,.action-grid a,.page-hero .container-xl').forEach(el=>el.classList.add('sb-reveal'));
  if(!reduced && 'IntersectionObserver' in window){
    const io=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');io.unobserve(entry.target)}}),{threshold:.08,rootMargin:'0px 0px -35px 0px'});
    document.querySelectorAll('.sb-reveal').forEach(el=>io.observe(el));
  }else document.querySelectorAll('.sb-reveal').forEach(el=>el.classList.add('is-visible'));
  document.querySelectorAll('[data-confirm]').forEach(el=>el.addEventListener('click',e=>{if(!window.confirm(el.dataset.confirm||'Continue?'))e.preventDefault()}));
  const stage=document.querySelector('[data-tilt]');
  if(stage&&!reduced&&window.matchMedia('(pointer:fine)').matches){
    stage.addEventListener('pointermove',e=>{const r=stage.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;stage.style.setProperty('--ry',`${x*7}deg`);stage.style.setProperty('--rx',`${-y*6}deg`)});
    stage.addEventListener('pointerleave',()=>{stage.style.setProperty('--ry','0deg');stage.style.setProperty('--rx','0deg')});
  }
  if(!reduced&&window.matchMedia('(pointer:fine)').matches){
    document.querySelectorAll('.metric-card,.product-card').forEach(card=>{
      card.addEventListener('pointermove',e=>{const r=card.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;card.style.transform=`perspective(900px) rotateX(${-y*2.2}deg) rotateY(${x*2.2}deg) translateY(-3px)`});
      card.addEventListener('pointerleave',()=>{card.style.transform=''})
    });
  }
});


/* Global page interactions: reveal, focus affordances, safe tilt on visual cards */
document.addEventListener('DOMContentLoaded',()=>{
 const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 const targets=document.querySelectorAll('.sb-main section,.sb-main .panel,.sb-main .card,.sb-main .table-responsive,.sb-main .auth-card,.sb-main .page-heading');
 targets.forEach((el,i)=>{if(!el.classList.contains('sb-reveal')){el.classList.add('sb-reveal');el.style.transitionDelay=`${Math.min(i%5,4)*45}ms`}});
 if(!reduce&&'IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');observer.unobserve(e.target)}}),{threshold:.04});document.querySelectorAll('.sb-reveal').forEach(el=>observer.observe(el))}else document.querySelectorAll('.sb-reveal').forEach(el=>el.classList.add('is-visible'));
 document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',()=>{const btn=form.querySelector('button[type="submit"],button:not([type]),input[type="submit"]');if(btn&&!btn.disabled){btn.dataset.originalText=btn.textContent;btn.disabled=true;btn.classList.add('is-submitting');setTimeout(()=>{btn.disabled=false;btn.classList.remove('is-submitting')},5000)}}));
});
