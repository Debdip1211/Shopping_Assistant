// Background service worker.
//
// In Manifest V3 the "background" is a service worker: a script Chrome starts
// when needed and stops when idle. It has no page of its own and can't see
// websites. Its only job here is one setting: clicking the toolbar icon should
// open our side panel (instead of doing nothing).

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.error("Could not set side panel behavior:", error));
});
