/**
 * Expo config plugin: make the background service legal on modern Android.
 *
 * react-native-background-actions declares its service without a
 * `foregroundServiceType`. That was fine when it was written; since API 34,
 * starting a foreground service with no declared type throws
 * `MissingForegroundServiceTypeException` and kills the app. This project
 * targets API 36, so without this plugin the app crashes the instant the
 * engine starts.
 *
 * Type choice: `specialUse` rather than `dataSync`.
 *
 * `dataSync` looks like the natural fit, but since API 35 Android caps
 * dataSync foreground services at roughly 6 hours per 24, after which the
 * system stops them. For a trading loop that means quietly ceasing to manage
 * an open position part-way through a day — the worst possible failure mode,
 * because nothing visibly breaks. `specialUse` carries no such cap. It
 * normally requires a justification during Play Store review, which does not
 * apply to an app installed directly.
 *
 * The `<service>` element here does not replace the library's; the manifest
 * merger folds these attributes into it.
 */

const { AndroidConfig, withAndroidManifest } = require('@expo/config-plugins');

const SERVICE_NAME = 'com.asterinet.react.bgactions.RNBackgroundActionsTask';
const PERMISSION = 'android.permission.FOREGROUND_SERVICE_SPECIAL_USE';

module.exports = (config) =>
  withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults;

    // 1. The typed permission that pairs with the service type.
    manifest.manifest['uses-permission'] = manifest.manifest['uses-permission'] ?? [];
    const already = manifest.manifest['uses-permission'].some(
      (p) => p.$?.['android:name'] === PERMISSION,
    );
    if (!already) {
      manifest.manifest['uses-permission'].push({ $: { 'android:name': PERMISSION } });
    }

    // 2. Merge the type onto the library's service declaration.
    const application = AndroidConfig.Manifest.getMainApplicationOrThrow(manifest);
    application.service = application.service ?? [];

    const existing = application.service.find((s) => s.$?.['android:name'] === SERVICE_NAME);
    const attributes = {
      'android:name': SERVICE_NAME,
      'android:foregroundServiceType': 'specialUse',
      'tools:node': 'merge',
    };

    const property = [
      {
        $: {
          'android:name': 'android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE',
          // Read by a human during review; describes what the service is for.
          'android:value': 'Runs the trading strategy loop while the app is in the background',
        },
      },
    ];

    if (existing) {
      Object.assign(existing.$, attributes);
      existing.property = property;
    } else {
      application.service.push({ $: attributes, property });
    }

    // The merger needs the tools namespace for tools:node to mean anything.
    manifest.manifest.$ = manifest.manifest.$ ?? {};
    if (!manifest.manifest.$['xmlns:tools']) {
      manifest.manifest.$['xmlns:tools'] = 'http://schemas.android.com/tools';
    }

    return cfg;
  });
