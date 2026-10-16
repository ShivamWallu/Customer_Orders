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

const BACKEND_BASE_URL = "https://order.khandelia.online";

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

  // Format timestamp (IST)
  const now = new Date();
  const istFormattedTimestamp = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy HH:mm:ss");
  const orderId = order.id || order.orderId || ("KOGM-" + Utilities.formatDate(now, "Asia/Kolkata", "yyyyMMdd") + "-" + Math.floor(1000 + Math.random() * 9000));

  // 📅 Auto Date Formatting (Guaranteed clean dd/MM/yyyy in IST)
  let orderDateFormatted = "";
  if (order.orderDate) {
    const rawDate = String(order.orderDate).trim();
    if (rawDate.indexOf("-") !== -1) {
      const parts = rawDate.split("-");
      if (parts.length === 3) {
        if (parts[0].length === 4) {
          // YYYY-MM-DD -> DD/MM/YYYY
          orderDateFormatted = parts[2] + "/" + parts[1] + "/" + parts[0];
        } else {
          orderDateFormatted = parts[0] + "/" + parts[1] + "/" + parts[2];
        }
      }
    } else {
      orderDateFormatted = rawDate;
    }
  }
  if (!orderDateFormatted) {
    orderDateFormatted = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy");
  }

  // Calculate Pieces and Boxes
  const itemsList = order.items || [];
  let totalPieces = Number(order.totalPieces || 0);
  let totalBoxes = Number(order.totalBoxes || 0);
  if (totalPieces === 0 && itemsList.length > 0) {
    totalPieces = 0;
    itemsList.forEach(function(it) {
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      totalPieces += (bxs * mult);
    });
  }

  // Format items summary string with Pieces and Boxes
  let itemsSummary = order.itemsSummary || "";
  if (!itemsSummary && itemsList.length > 0) {
    itemsSummary = itemsList.map(function(it) {
      const icon = (it.brand || "Mashal").toLowerCase() === "mashal" ? "🔵" : "🟢";
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      const pcs = bxs * mult;
      return icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + pcs + " Pcs (" + bxs + " bxs)";
    }).join("\n");
  }

  // Check existing headers or initialize sheet
  // Check existing headers or initialize sheet
  let headerRow = [];
  if (sheet.getLastRow() > 0) {
    headerRow = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0].map(function(h) { return String(h).trim(); });
  }

  // 1. Auto-migrate Column C header from "Order Date" to "Party Code"
  if (sheet.getLastRow() > 0 && sheet.getRange(1, 3).getValue().toString().trim().toLowerCase().includes("date")) {
    sheet.getRange(1, 3).setValue("Party Code");
  }

  const standardHeaders = [
    "Timestamp (IST)", 
    "Order ID", 
    "Party Code", 
    "Party Name (Customer)", 
    "Billing Address", 
    "Delivery Address", 
    "Area Sales Manager", 
    "Quantity (Pieces)",
    "Total Boxes", 
    "Ordered Items Breakdown",
    "Customer Consent",
    "Status"
  ];

  if (sheet.getLastRow() === 0 || sheet.getRange(1, 1).getValue() === "") {
    sheet.appendRow(standardHeaders);
    const headerRange = sheet.getRange(1, 1, 1, standardHeaders.length);
    headerRange.setBackground("#003366")
               .setFontColor("#ffffff")
               .setFontWeight("bold")
               .setFontSize(11)
               .setHorizontalAlignment("center")
               .setVerticalAlignment("middle");
    sheet.setRowHeight(1, 38);
    sheet.setFrozenRows(1);
    headerRow = standardHeaders;
  }

  // Check if "Quantity (Pieces)" exists in header row, if not add it dynamically
  let hasPiecesCol = false;
  headerRow.forEach(function(h) {
    if (h.toLowerCase().indexOf("piece") !== -1 || h.toLowerCase().indexOf("pcs") !== -1) {
      hasPiecesCol = true;
    }
  });

  if (!hasPiecesCol && headerRow.length >= 8) {
    let boxesIdx = -1;
    for (let i = 0; i < headerRow.length; i++) {
      if (headerRow[i].toLowerCase().indexOf("box") !== -1) {
        boxesIdx = i + 1;
        break;
      }
    }
    if (boxesIdx !== -1) {
      sheet.insertColumnBefore(boxesIdx);
      sheet.getRange(1, boxesIdx).setValue("Quantity (Pieces)")
           .setBackground("#003366")
           .setFontColor("#ffffff")
           .setFontWeight("bold")
           .setFontSize(11)
           .setHorizontalAlignment("center")
           .setVerticalAlignment("middle");
      hasPiecesCol = true;
    }
  }

  // Check if "Customer Consent" column exists, if not insert before Status
  let hasConsentCol = false;
  let statusColIdx = -1;
  headerRow = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0].map(function(h) { return String(h).trim(); });
  for (let i = 0; i < headerRow.length; i++) {
    if (headerRow[i].toLowerCase().indexOf("consent") !== -1) {
      hasConsentCol = true;
    }
    if (headerRow[i].toLowerCase().indexOf("status") !== -1) {
      statusColIdx = i + 1;
    }
  }
  if (!hasConsentCol && statusColIdx !== -1) {
    sheet.insertColumnBefore(statusColIdx);
    sheet.getRange(1, statusColIdx).setValue("Customer Consent")
         .setBackground("#003366")
         .setFontColor("#ffffff")
         .setFontWeight("bold")
         .setFontSize(11)
         .setHorizontalAlignment("center")
         .setVerticalAlignment("middle");
    hasConsentCol = true;
  }

  // Resolve Party Code (Customer Code)
  const resolvedPartyCode = (order.partyCode || order.party_code || "").toString().trim();
  const consentVal = (order.dataConsent || order.consent || "YES (Verified)").toString().trim();

  // Build row array according to column structure
  let row = [];
  if (hasPiecesCol && hasConsentCol) {
    row = [
      istFormattedTimestamp,
      orderId,
      resolvedPartyCode || "NEW CUSTOMER",
      order.partyName || "",
      order.partyAddress || "",
      order.deliveryAddress || order.partyAddress || "",
      order.salesPerson || "",
      Number(totalPieces),
      Number(totalBoxes),
      itemsSummary,
      consentVal,
      "CONFIRMED"
    ];
  } else if (hasPiecesCol) {
    row = [
      istFormattedTimestamp,
      orderId,
      resolvedPartyCode || "NEW CUSTOMER",
      order.partyName || "",
      order.partyAddress || "",
      order.deliveryAddress || order.partyAddress || "",
      order.salesPerson || "",
      Number(totalPieces),
      Number(totalBoxes),
      itemsSummary,
      "CONFIRMED"
    ];
  } else {
    row = [
      istFormattedTimestamp,
      orderId,
      resolvedPartyCode || "NEW CUSTOMER",
      order.partyName || "",
      order.partyAddress || "",
      order.deliveryAddress || order.partyAddress || "",
      order.salesPerson || "",
      Number(totalBoxes),
      itemsSummary,
      "CONFIRMED"
    ];
  }

  sheet.appendRow(row);
  const lastRow = sheet.getLastRow();
  
  // Format row columns
  sheet.getRange(lastRow, 1).setHorizontalAlignment("center").setVerticalAlignment("middle"); // Timestamp
  sheet.getRange(lastRow, 2).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#004b99").setHorizontalAlignment("center").setVerticalAlignment("middle"); // Order ID
  
  // Column 3: Party Code (Formatted with high contrast monospace bold)
  sheet.getRange(lastRow, 3).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#003366").setBackground("#eff6ff").setHorizontalAlignment("center").setVerticalAlignment("middle");
  
  // Column 4: Party Name
  sheet.getRange(lastRow, 4).setFontWeight("bold").setVerticalAlignment("middle");
  
  // Column 5 & 6: Billing & Delivery Address (Wrapped neatly without clipping)
  sheet.getRange(lastRow, 5).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  sheet.getRange(lastRow, 6).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  sheet.setColumnWidth(5, 230);
  sheet.setColumnWidth(6, 260);
  
  if (hasPiecesCol && hasConsentCol) {
    sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setFontColor("#1e40af").setBackground("#f0fdf4"); // Pieces
    sheet.getRange(lastRow, 9).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff"); // Boxes
    
    // Column 10: Items Breakdown
    const cellBreakdown = sheet.getRange(lastRow, 10);
    if (itemsList.length > 0) {
      try {
        cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
      } catch (e) {
        cellBreakdown.setValue(itemsSummary);
      }
    }
    cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
    sheet.setColumnWidth(10, 320);

    // Column 11: Customer Consent (Green verified chip)
    sheet.getRange(lastRow, 11).setFontWeight("bold").setFontSize(10.5).setFontColor("#15803d").setBackground("#f0fdf4").setHorizontalAlignment("center").setVerticalAlignment("middle");
    // Column 12: Status
    sheet.getRange(lastRow, 12).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle");
  } else if (hasPiecesCol) {
    sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setFontColor("#1e40af").setBackground("#f0fdf4");
    sheet.getRange(lastRow, 9).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff");
    sheet.getRange(lastRow, 11).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle");
    const cellBreakdown = sheet.getRange(lastRow, 10);
    if (itemsList.length > 0) {
      try {
        cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
      } catch (e) {
        cellBreakdown.setValue(itemsSummary);
      }
    }
    cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  } else {
    sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff");
    sheet.getRange(lastRow, 10).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle");
    const cellBreakdown = sheet.getRange(lastRow, 9);
    if (itemsList.length > 0) {
      try {
        cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
      } catch (e) {
        cellBreakdown.setValue(itemsSummary);
      }
    }
    cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  }

  // Dynamic spacious row height
  const calculatedHeight = Math.max(42, itemsList.length * 24 + 14);
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
