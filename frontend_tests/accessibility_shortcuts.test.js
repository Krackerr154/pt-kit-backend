const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');

// 6.1 Ctrl+Enter confirms from the review modal
const kdSrc=html.match(/function handleReviewModalKeydown\(e\)\{[^\n]*/)[0];
const kdCtx={document:{getElementById:()=>({hidden:false})}};
vm.createContext(kdCtx);
vm.runInContext(kdSrc,kdCtx);
let confirmed=0,closed=0;
kdCtx.confirmReviewedStart=()=>confirmed++;
kdCtx.closeReviewModal=()=>closed++;
const ev=(key,mods)=>Object.assign({key:key,preventDefault(){this.prevented=true;},prevented:false},mods||{});
const ctrlEnter=ev('Enter',{ctrlKey:true});
kdCtx.handleReviewModalKeydown(ctrlEnter);
assert.strictEqual(confirmed,1,'Ctrl+Enter triggers confirmReviewedStart');
assert.strictEqual(ctrlEnter.prevented,true,'Ctrl+Enter prevents default');
const cmdEnter=ev('Enter',{metaKey:true});
kdCtx.handleReviewModalKeydown(cmdEnter);
assert.strictEqual(confirmed,2,'Cmd+Enter also confirms (macOS)');
const plainEnter=ev('Enter');
kdCtx.handleReviewModalKeydown(plainEnter);
assert.strictEqual(confirmed,2,'plain Enter does not confirm');
assert.strictEqual(plainEnter.prevented,false,'plain Enter left alone');
const esc=ev('Escape');
kdCtx.handleReviewModalKeydown(esc);
assert.strictEqual(closed,1,'Escape closes the review modal');

// 6.1/6.2 consolidated global shortcuts
const gsSrc=html.match(/function handleGlobalShortcut\(e\)\{[^]*?\n\}/)[0];
let modeHelpClosed=0,menuClosed=0,reviewClosed=0,stopClosed=0,sampleFocused=0;
const els={reviewModal:{hidden:true},stopModal:{hidden:true},sampleName:{focus(){sampleFocused++;}}};
const gsCtx={
    document:{getElementById:(id)=>els[id]||null,querySelectorAll:()=>[]},
    Array,
    toggleModeHelp:()=>modeHelpClosed++,
    toggleUtilitiesMenu:()=>menuClosed++,
    closeReviewModal:()=>reviewClosed++,
    closeStopModal:()=>stopClosed++,
};
vm.createContext(gsCtx);
vm.runInContext(gsSrc,gsCtx);
const ctrlS=ev('s',{ctrlKey:true});
gsCtx.handleGlobalShortcut(ctrlS);
assert.strictEqual(ctrlS.prevented,true,'Ctrl+S prevents the browser save dialog');
assert.strictEqual(sampleFocused,1,'Ctrl+S focuses the sample name field');
els.reviewModal.hidden=false;
const ctrlS2=ev('s',{ctrlKey:true});
gsCtx.handleGlobalShortcut(ctrlS2);
assert.strictEqual(sampleFocused,1,'Ctrl+S never steals focus from an open modal');
els.reviewModal.hidden=true;
const escG=ev('Escape');
gsCtx.handleGlobalShortcut(escG);
assert.strictEqual(modeHelpClosed,1,'Escape closes the mode help tooltip');
assert.strictEqual(menuClosed,1,'Escape closes the utilities menu');
assert.strictEqual(reviewClosed,0,'no modal open: modal closers not called');
els.stopModal.hidden=false;
gsCtx.handleGlobalShortcut(ev('Escape'));
assert.strictEqual(stopClosed,1,'Escape closes an open stop modal');
els.stopModal.hidden=false;els.reviewModal.hidden=false;
gsCtx.handleGlobalShortcut(ev('Escape'));
assert.strictEqual(reviewClosed,1,'Escape closes the review modal first');
assert.strictEqual(stopClosed,1,'review modal takes precedence over stop modal');
els.reviewModal.hidden=true;els.stopModal.hidden=true;
const used=ev('Escape');used.defaultPrevented=true;
const before=modeHelpClosed+menuClosed;
gsCtx.handleGlobalShortcut(used);
assert.strictEqual(modeHelpClosed+menuClosed,before,'already-handled Escape is ignored');

// 6.1 shortcut hints on primary actions
assert(/id="confirmReview"[^>]*title="Confirm and start \(Ctrl\+Enter\)"/.test(html),'confirm button advertises Ctrl+Enter');
assert(/id="cancelReview"[^>]*title="Back to edit \(Escape\)"/.test(html),'cancel button advertises Escape');
assert(/id="sampleName"[^>]*title="[^"]*Ctrl\+S[^"]*"/.test(html),'sample field advertises Ctrl+S');

// 6.2 ARIA audit
assert(/id="reviewModal"[^>]*class="modal-backdrop"[^>]*hidden><div class="modal review-sheet" role="dialog" aria-modal="true" aria-labelledby="reviewTitle"/.test(html),'review modal is a labelled modal dialog');
assert(/id="stopModal"[^>]*><div class="modal" role="dialog" aria-modal="true" aria-labelledby="stopModalTitle"/.test(html),'stop modal is a labelled modal dialog');
assert(/id="startHint"[^>]*aria-live="polite"/.test(html),'start gating hint announces state changes');
assert(/id="reviewStartBtn"[^>]*aria-describedby="hardwareLockNote"/.test(html),'start button is described by the hardware lock explanation');
assert(/role="radiogroup"/.test(html),'illumination segmented control is a radiogroup');
assert(kdSrc.includes("e.key==='Tab'"),'review modal traps Tab focus');
const fm=html.match(/function finishReviewModal\(restoreFocus\)\{[^\n]*/)[0];
assert(fm.includes('reviewModalOpener')&&fm.includes('.focus'),'closing the review modal restores focus to the opener');
assert(/li\.id = sel\.id \+ '-opt-' \+ i;/.test(html),'custom dropdown options carry stable ids');
assert(html.includes("btn.setAttribute('aria-activedescendant', opts[i].id)"),'active dropdown option is exposed via aria-activedescendant');
assert(html.includes("btn.removeAttribute('aria-activedescendant')"),'aria-activedescendant clears when the dropdown closes');
assert(/document\.addEventListener\('keydown',handleGlobalShortcut\)/.test(html),'global shortcut handler is registered');

console.log('Accessibility & shortcuts: PASS');
