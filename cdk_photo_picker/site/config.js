// Copy this file to config.js and fill values.
// Exposes a global `AppConfig` used by main.js.

window.AppConfig = {
  google: {
    // OAuth 2.0 Client ID for Web (from Google Cloud Console)
    clientId: "xxxxxxxxxx.apps.googleusercontent.com",
    // Picker API scopes
    scopes: ["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"],
  },
  upload: {
    // Either provide a presign endpoint URL that returns { url } or { url, fields }
    presignEndpoint: "https://xxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/presign",
    // Endpoint for listing & deleting uploaded objects
    manageEndpoint: "https://xxxxx.execute-api.ap-northeast-1.amazonaws.com/prod/uploads",
    // Optional: prefix for S3 object keys, e.g., "uploads/"
    s3KeyPrefix: "uploads/"
  }
};
