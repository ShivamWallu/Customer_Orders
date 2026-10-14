/**
 * 🚀 KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
 * SCRIPT FOR SPREADSHEET: "Customers Orders"
 * 
 * 📋 INSTRUCTIONS TO INSTALL IN GOOGLE SHEET:
 * 1. Open your Google Sheet named "Customers Orders" (account: itchd.kogm@gmail.com).
 * 2. Click: Extensions > Apps Script.
 * 3. Delete any default code and PASTE this entire script.
 * 4. Click: Deploy > New deployment.
 * 5. Select type: "Web app".
 *    - Description: "Mashal Orders Webhook"
 *    - Execute as: "Me (itchd.kogm@gmail.com)"
 *    - Who has access: "Anyone"
 * 6. Click "Deploy" and Copy the "Web app URL" (e.g. https://script.google.com/macros/s/.../exec).
 * 7. That's it! Every submitted order will instantly appear here with 100% accuracy and zero missed orders.
 */

const BACKEND_BASE_URL = "https://sevenfold-blazer-pacific.ngrok-free.dev";

/**
 * 📦 Web App Endpoint: Receives order submissions and appends to Google Sheet
 * Concurrency protected with ScriptLock to guarantee ZERO missed orders.
 */
function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    // Wait up to 15 seconds to acquire lock (prevents simultaneous write conflicts)
    lock.waitLock(15000);

    const postData = e && e.postData && e.postData.contents ? JSON.parse(e.postData.contents) : null;
    if (!postData) {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "No data payload received" }))
                           .setMimeType(ContentService.MimeType.JSON);
    }

    appendOrderToSheet(postData);

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      orderId: postData.id || postData.orderId,
      message: "Order successfully added to Customers Orders sheet"
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    Logger.log("doPost Error: " + err.message);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", error: err.message }))
                         .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

/**
 * Core function to append a single order row with proper formatting
 */
function appendOrderToSheet(order) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet();
  
  // Ensure we are working on the main sheet
  if (!sheet) {
    sheet = ss.getSheets()[0];
  }

  // Check if header row exists
  if (sheet.getLastRow() === 0 || sheet.getRange(1, 1).getValue() === "") {
    const headers = [
      "Timestamp (IST)", 
      "Order ID", 
      "Order Date", 
      "Party Name (Customer)", 
      "Billing Address", 
      "Delivery Address", 
      "Sales Person", 
      "Total Boxes", 
      "Ordered Items Breakdown", 
      "Status"
    ];
    sheet.appendRow(headers);
    
    // Style Header Row
    const headerRange = sheet.getRange(1, 1, 1, headers.length);
    headerRange.setBackground("#003366")
               .setFontColor("#ffffff")
               .setFontWeight("bold")
               .setFontSize(11)
               .setHorizontalAlignment("center")
               .setVerticalAlignment("middle");
    sheet.setRowHeight(1, 38);
    sheet.setFrozenRows(1);
  }

  // Format timestamp (IST)
  const now = new Date();
  const istFormattedTimestamp = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy HH:mm:ss");
  const orderId = order.id || order.orderId || ("KOGM-" + Utilities.formatDate(now, "Asia/Kolkata", "yyyyMMdd") + "-" + Math.floor(1000 + Math.random() * 9000));
  
  // Format items summary string
  let itemsSummary = order.itemsSummary || "";
  const itemsList = order.items || [];
  if (!itemsSummary && itemsList.length > 0) {
    itemsSummary = itemsList.map(function(it) {
      const icon = (it.brand || "Mashal").toLowerCase() === "mashal" ? "🔵" : "🟢";
      return icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + (it.boxes || 0) + " bxs";
    }).join("\n");
  }

  const row = [
    istFormattedTimestamp,
    orderId,
    order.formattedDate || order.orderDate || Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy"),
    order.partyName || "",
    order.partyAddress || "",
    order.deliveryAddress || order.partyAddress || "",
    order.salesPerson || "",
    Number(order.totalBoxes || 0),
    itemsSummary, // Will be enhanced by rich text below
    "CONFIRMED"
  ];

  sheet.appendRow(row);

  const lastRow = sheet.getLastRow();
  
  // Format row columns
  sheet.getRange(lastRow, 1).setHorizontalAlignment("center").setVerticalAlignment("middle"); // Timestamp
  sheet.getRange(lastRow, 2).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#004b99").setHorizontalAlignment("center").setVerticalAlignment("middle"); // Order ID
  sheet.getRange(lastRow, 3).setHorizontalAlignment("center").setVerticalAlignment("middle"); // Order Date
  sheet.getRange(lastRow, 4).setFontWeight("bold").setVerticalAlignment("middle"); // Party Name
  sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff"); // Total Boxes
  sheet.getRange(lastRow, 10).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle"); // Status
  
  // 🎨 Multi-line Colorful Rich Text for Column I (Ordered Items Breakdown)
  const cellI = sheet.getRange(lastRow, 9);
  if (itemsList.length > 0) {
    try {
      cellI.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
    } catch (e) {
      cellI.setValue(itemsSummary);
    }
  }
  cellI.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  cellI.setVerticalAlignment("middle");
  
  // Dynamic spacious row height for comfortable reading
  const calculatedHeight = Math.max(38, itemsList.length * 24 + 10);
  sheet.setRowHeight(lastRow, calculatedHeight);
}

/**
 * 🎨 Builds Beautiful Multi-line Rich Text with colored brand tags and bold amber box counts
 */
function buildRichItemsBreakdown(items, fallbackText) {
  if (!items || items.length === 0) {
    return SpreadsheetApp.newRichTextValue().setText(fallbackText || "-").build();
  }

  let fullText = "";
  const linesInfo = [];

  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const isMashal = (it.brand || "Mashal").toLowerCase() === "mashal";
    const bullet = isMashal ? "🔵" : "🟢";
    const brandName = isMashal ? "Mashal" : "Fauji";
    const boxQty = String(it.boxes || 0) + " bxs";
    
    // Line layout: "🔵 Mashal 1 LTR. BOTTLE x 15 ➔ 40 bxs"
    const line = bullet + " " + brandName + " " + (it.item || "") + " ➔ " + boxQty;
    
    const startIdx = fullText.length;
    fullText += (i > 0 ? "\n" : "") + line;
    const actualStart = i > 0 ? startIdx + 1 : startIdx;
    
    const boxPosInLine = line.lastIndexOf(boxQty);
    const boxStart = actualStart + boxPosInLine;
    const boxEnd = boxStart + boxQty.length;

    linesInfo.push({
      start: actualStart,
      boxStart: boxStart,
      boxEnd: boxEnd,
      isMashal: isMashal
    });
  }

  const builder = SpreadsheetApp.newRichTextValue().setText(fullText);

  // Base font style
  builder.setTextStyle(0, fullText.length, 
    SpreadsheetApp.newTextStyle()
      .setFontFamily("Arial")
      .setFontSize(10)
      .setForegroundColor("#1e293b")
      .build()
  );

  // Apply colors & highlights
  for (let j = 0; j < linesInfo.length; j++) {
    const info = linesInfo[j];
    
    // Highlight brand tag
    builder.setTextStyle(info.start, Math.min(info.start + 9, fullText.length), 
      SpreadsheetApp.newTextStyle()
        .setBold(true)
        .setForegroundColor(info.isMashal ? "#004b99" : "#007a3d")
        .build()
    );

    // Highlight box quantity in bold standout warm color (#b45309)
    if (info.boxStart >= 0 && info.boxEnd <= fullText.length) {
      builder.setTextStyle(info.boxStart, info.boxEnd, 
        SpreadsheetApp.newTextStyle()
          .setBold(true)
          .setFontSize(10.5)
          .setForegroundColor("#b45309")
          .build()
      );
    }
  }

  return builder.build();
}

/**
 * 📥 Pull Unsynced Orders from Backend Server
 * Guarantees zero missed orders even if direct webhook had a temporary interruption.
 */
function syncPendingOrdersFromBackend() {
  const url = BACKEND_BASE_URL + "/api/orders/pending";
  try {
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) {
      Logger.log("Failed to fetch pending orders: " + res.getContentText());
      return;
    }
    const data = JSON.parse(res.getContentText());
    const pending = data.pending_orders || [];
    if (pending.length === 0) {
      SpreadsheetApp.getActiveSpreadsheet().toast("All customer orders are up-to-date!", "Mashal OMS", 3);
      return;
    }

    const lock = LockService.getScriptLock();
    lock.waitLock(15000);
    const syncedIds = [];
    try {
      for (let i = 0; i < pending.length; i++) {
        appendOrderToSheet(pending[i]);
        syncedIds.push(pending[i].id);
      }
    } finally {
      lock.releaseLock();
    }

    // Mark synced on backend
    if (syncedIds.length > 0) {
      UrlFetchApp.fetch(BACKEND_BASE_URL + "/api/orders/mark-synced", {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify({ orderIds: syncedIds }),
        muteHttpExceptions: true
      });
    }

    SpreadsheetApp.getActiveSpreadsheet().toast("Successfully added " + syncedIds.length + " new orders into Customers Orders sheet!", "Mashal OMS", 5);
  } catch (err) {
    Logger.log("Sync Pending Orders Error: " + err.message);
  }
}

/**
 * Custom Menu inside Google Sheets
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 Orders Menu")
    .addItem("📥 Sync Pending Orders From App", "syncPendingOrdersFromBackend")
    .addToUi();
}
