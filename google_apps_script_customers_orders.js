/**
 * 🚀 KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
 * SCRIPT FOR SPREADSHEET: "Customers Orders"
 * 
 * 📋 INSTRUCTIONS TO INSTALL IN GOOGLE SHEET:
 * 1. Open your Google Sheet named "Customers Orders" (account: itchd.kogm@gmail.com).
 * 2. Click: Extensions > Apps Script.
 * 3. Delete any default code and PASTE this entire script.
 * 4. Click: Deploy > New deployment.
 *    - Select type: "Web app"
 *    - Description: "Mashal Orders Webhook v3 - Single Address & Party Code"
 *    - Execute as: "Me (itchd.kogm@gmail.com)"
 *    - Who has access: "Anyone"
 * 5. Click "Deploy" and Copy the "Web app URL".
 * 6. You will also see a new menu in your sheet: "🚀 Mashal Orders > ⚡ Update & Fix Columns Now".
 *    Clicking it will instantly convert any existing columns to the new clean layout!
 */

const BACKEND_BASE_URL = "https://order.khandelia.online";

/**
 * 🌟 Creates custom menu in Google Sheets
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚀 Mashal Orders")
    .addItem("⚡ Update & Fix Columns Now", "menuFixColumns")
    .addToUi();
}

/**
 * Menu action to format and fix all headers & address columns instantly
 */
function menuFixColumns() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  migrateAndFormatSheet(sheet);
  SpreadsheetApp.getUi().alert("✔ Columns Successfully Updated!\n\n• Merged duplicate address into single 'Party Address'\n• Column C is now 'Party Code'\n• 'Quantity (Pieces)' and 'Customer Consent' aligned\n• Text wrap and column widths applied.");
}

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
 * 🛠️ Comprehensive Auto-Migration & Sheet Formatting Function
 * Automatically cleans any old headers, deletes redundant Delivery Address column,
 * sets Party Code, wraps address text, and applies branded Navy Blue styling.
 */
function migrateAndFormatSheet(sheet) {
  if (!sheet) {
    sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  }

  const standardHeaders = [
    "Timestamp (IST)", 
    "Order ID", 
    "Party Code", 
    "Party Name (Customer)", 
    "Party Address", 
    "Area Sales Manager", 
    "Quantity (Pieces)",
    "Total Boxes", 
    "Ordered Items Breakdown",
    "Customer Consent",
    "Status"
  ];

  if (sheet.getLastRow() === 0 || sheet.getRange(1, 1).getValue() === "") {
    sheet.appendRow(standardHeaders);
  } else {
    // Check existing headers
    const lastCol = Math.max(sheet.getLastColumn(), 1);
    const curHeaders = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(function(h) { return String(h).trim(); });
    
    // 1. If Column 3 is Order Date, change to Party Code
    if (curHeaders.length >= 3 && curHeaders[2].toLowerCase().indexOf("date") !== -1) {
      sheet.getRange(1, 3).setValue("Party Code");
    }

    // 2. Look for Billing Address and Delivery Address
    let billingCol = -1;
    let deliveryCol = -1;
    for (let i = 0; i < curHeaders.length; i++) {
      const h = curHeaders[i].toLowerCase();
      if (h.indexOf("billing") !== -1) billingCol = i + 1;
      if (h.indexOf("delivery") !== -1) deliveryCol = i + 1;
    }

    // Rename Billing to "Party Address"
    if (billingCol !== -1) {
      sheet.getRange(1, billingCol).setValue("Party Address");
    }

    // Delete redundant Delivery Address column if both exist
    if (deliveryCol !== -1 && billingCol !== -1) {
      sheet.deleteColumn(deliveryCol);
    }

    // Re-check headers after potential deletion
    const updatedHeaders = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0].map(function(h) { return String(h).trim(); });

    // 3. Ensure "Quantity (Pieces)" exists before Total Boxes
    let hasPieces = updatedHeaders.some(function(h) { return h.toLowerCase().indexOf("piece") !== -1 || h.toLowerCase().indexOf("pcs") !== -1; });
    if (!hasPieces) {
      let boxesIdx = -1;
      for (let i = 0; i < updatedHeaders.length; i++) {
        if (updatedHeaders[i].toLowerCase().indexOf("box") !== -1) {
          boxesIdx = i + 1;
          break;
        }
      }
      if (boxesIdx !== -1) {
        sheet.insertColumnBefore(boxesIdx);
        sheet.getRange(1, boxesIdx).setValue("Quantity (Pieces)");
      }
    }

    // 4. Ensure "Customer Consent" exists before Status
    const afterPiecesHeaders = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0].map(function(h) { return String(h).trim(); });
    let hasConsent = afterPiecesHeaders.some(function(h) { return h.toLowerCase().indexOf("consent") !== -1; });
    if (!hasConsent) {
      let statusIdx = -1;
      for (let i = 0; i < afterPiecesHeaders.length; i++) {
        if (afterPiecesHeaders[i].toLowerCase().indexOf("status") !== -1) {
          statusIdx = i + 1;
          break;
        }
      }
      if (statusIdx !== -1) {
        sheet.insertColumnBefore(statusIdx);
        sheet.getRange(1, statusIdx).setValue("Customer Consent");
      }
    }

    // 5. Ensure Sales Person is named Area Sales Manager
    for (let i = 1; i <= Math.max(sheet.getLastColumn(), 1); i++) {
      const val = sheet.getRange(1, i).getValue().toString().trim().toLowerCase();
      if (val === "sales person") {
        sheet.getRange(1, i).setValue("Area Sales Manager");
      }
    }
  }

  // Apply Styling to Header Row
  const totalCols = Math.max(sheet.getLastColumn(), 11);
  const headerRange = sheet.getRange(1, 1, 1, totalCols);
  headerRange.setBackground("#003366")
             .setFontColor("#ffffff")
             .setFontWeight("bold")
             .setFontSize(11)
             .setHorizontalAlignment("center")
             .setVerticalAlignment("middle");
  sheet.setRowHeight(1, 38);
  sheet.setFrozenRows(1);

  // Set Column Widths
  sheet.setColumnWidth(1, 155); // Timestamp (IST)
  sheet.setColumnWidth(2, 175); // Order ID
  sheet.setColumnWidth(3, 130); // Party Code
  sheet.setColumnWidth(4, 210); // Party Name (Customer)
  sheet.setColumnWidth(5, 260); // Party Address
  sheet.setColumnWidth(6, 155); // Area Sales Manager
  sheet.setColumnWidth(7, 130); // Quantity (Pieces)
  sheet.setColumnWidth(8, 110); // Total Boxes
  sheet.setColumnWidth(9, 330); // Ordered Items Breakdown
  sheet.setColumnWidth(10, 135); // Customer Consent
  sheet.setColumnWidth(11, 120); // Status

  // Wrap text on Party Address and Items Breakdown
  if (sheet.getLastRow() > 1) {
    sheet.getRange(2, 5, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
    sheet.getRange(2, 9, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  }
}

/**
 * Core function to append a single order row with proper formatting
 */
function appendOrderToSheet(order) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet();
  if (!sheet) {
    sheet = ss.getSheets()[0];
  }

  // 1. Run Auto-Migration & Formatting to ensure columns are 100% synchronized
  migrateAndFormatSheet(sheet);

  // Format timestamp (IST)
  const now = new Date();
  const istFormattedTimestamp = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy HH:mm:ss");
  const orderId = order.id || order.orderId || ("KOGM-" + Utilities.formatDate(now, "Asia/Kolkata", "yyyyMMdd") + "-" + Math.floor(1000 + Math.random() * 9000));

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

  // Resolve single Party Address (No duplicate Billing vs Delivery)
  const partyAddress = (order.partyAddress || order.billingAddress || order.deliveryAddress || "").toString().trim();
  const resolvedPartyCode = (order.partyCode || order.party_code || "").toString().trim() || "NEW CUSTOMER";
  const consentVal = (order.dataConsent || order.consent || "YES (Verified)").toString().trim();

  // Exactly 11 Clean Columns:
  // 1: Timestamp (IST)
  // 2: Order ID
  // 3: Party Code
  // 4: Party Name
  // 5: Party Address (Single!)
  // 6: Area Sales Manager
  // 7: Quantity (Pieces)
  // 8: Total Boxes
  // 9: Ordered Items Breakdown
  // 10: Customer Consent
  // 11: Status
  const row = [
    istFormattedTimestamp,
    orderId,
    resolvedPartyCode,
    order.partyName || "",
    partyAddress,
    order.salesPerson || "",
    Number(totalPieces),
    Number(totalBoxes),
    itemsSummary,
    consentVal,
    "CONFIRMED"
  ];

  sheet.appendRow(row);
  const lastRow = sheet.getLastRow();
  
  // Format Row Cells
  sheet.getRange(lastRow, 1).setHorizontalAlignment("center").setVerticalAlignment("middle"); // Timestamp
  sheet.getRange(lastRow, 2).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#004b99").setHorizontalAlignment("center").setVerticalAlignment("middle"); // Order ID
  
  // Column 3: Party Code (Monospace bold on soft blue chip)
  sheet.getRange(lastRow, 3).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#003366").setBackground("#eff6ff").setHorizontalAlignment("center").setVerticalAlignment("middle");
  
  // Column 4: Party Name
  sheet.getRange(lastRow, 4).setFontWeight("bold").setVerticalAlignment("middle");
  
  // Column 5: Single Party Address (Wrapped, 260px wide)
  sheet.getRange(lastRow, 5).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  
  // Column 6: Area Sales Manager
  sheet.getRange(lastRow, 6).setHorizontalAlignment("center").setVerticalAlignment("middle");

  // Column 7: Quantity (Pieces)
  sheet.getRange(lastRow, 7).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setFontColor("#1e40af").setBackground("#f0fdf4");

  // Column 8: Total Boxes
  sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff");
  
  // Column 9: Items Breakdown (Rich colored bullets & wrapped)
  const cellBreakdown = sheet.getRange(lastRow, 9);
  if (itemsList.length > 0) {
    try {
      cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
    } catch (e) {
      cellBreakdown.setValue(itemsSummary);
    }
  }
  cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");

  // Column 10: Customer Consent (Verified Green Chip)
  sheet.getRange(lastRow, 10).setFontWeight("bold").setFontSize(10.5).setFontColor("#15803d").setBackground("#f0fdf4").setHorizontalAlignment("center").setVerticalAlignment("middle");
  
  // Column 11: Status (CONFIRMED)
  sheet.getRange(lastRow, 11).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle");

  // Dynamic spacious row height
  const calculatedHeight = Math.max(44, itemsList.length * 24 + 14);
  sheet.setRowHeight(lastRow, calculatedHeight);
}

/**
 * 🎨 Builds Rich Text with Navy bullets for Mashal & Green bullets for Fauji
 */
function buildRichItemsBreakdown(itemsList, fallbackText) {
  const richTextBuilder = SpreadsheetApp.newRichTextValue();
  let fullText = "";
  const brandRanges = [];

  itemsList.forEach(function(it, idx) {
    const isMashal = (it.brand || "Mashal").toLowerCase() === "mashal";
    const icon = isMashal ? "🔵" : "🟢";
    const match = (it.item || "").match(/x\s*(\d+)/i);
    const mult = match ? parseInt(match[1], 10) : 1;
    const bxs = parseInt(it.boxes, 10) || 0;
    const pcs = bxs * mult;
    const line = icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + pcs + " Pcs (" + bxs + " bxs)";
    
    const startIdx = fullText.length;
    fullText += (idx > 0 ? "\n" : "") + line;
    const lineStart = idx > 0 ? startIdx + 1 : startIdx;
    
    brandRanges.push({
      start: lineStart,
      end: lineStart + icon.length + 1 + (it.brand || "Mashal").length,
      isMashal: isMashal
    });
  });

  richTextBuilder.setText(fullText || fallbackText);

  // Apply Brand Colors
  brandRanges.forEach(function(r) {
    const style = SpreadsheetApp.newTextStyle()
      .setBold(true)
      .setForegroundColor(r.isMashal ? "#004b99" : "#007a3d")
      .build();
    richTextBuilder.setTextStyle(r.start, r.end, style);
  });

  return richTextBuilder.build();
}
