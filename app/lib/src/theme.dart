/// One design system, so the app reads as a product rather than a control panel.
///
/// Every value here exists because it is used in more than one place. Spacing is a
/// 4-point scale, surfaces are three explicit depths rather than a dozen ad-hoc
/// greys, and type has four sizes. The constraint is the point: a tool that is
/// tuning colour and light must not itself be visually noisy, or the user cannot
/// tell whether a change was theirs or the interface's.
library;

import 'package:flutter/material.dart';

class Insets {
  static const double xs = 4, sm = 8, md = 12, lg = 16, xl = 24;
}

class Surfaces {
  /// Three depths: the app ground, panels raised off it, and controls on those.
  static const Color ground = Color(0xFF101318);
  static const Color panel = Color(0xFF161A20);
  static const Color raised = Color(0xFF1E242C);
  static const Color line = Color(0xFF2A313A);
  static const Color viewport = Color(0xFF0C0F13);

  static const Color accent = Color(0xFF6FD3A0);
  static const Color accentDim = Color(0xFF3E7D63);
  static const Color warn = Color(0xFFE2725B);
  static const Color ink = Color(0xFFE8EDF4);
  static const Color inkDim = Color(0xFF9AA5B3);
  static const Color inkFaint = Color(0xFF5D6875);
}

class Type {
  static const TextStyle title =
      TextStyle(fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: -0.1);
  static const TextStyle body = TextStyle(fontSize: 12.5, height: 1.35);
  static const TextStyle label =
      TextStyle(fontSize: 11.5, color: Surfaces.inkDim);
  static const TextStyle caption =
      TextStyle(fontSize: 10.5, color: Surfaces.inkFaint, height: 1.3);
  static const TextStyle section = TextStyle(
      fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w600,
      color: Surfaces.inkFaint);
}

ThemeData tesseraTheme() {
  const scheme = ColorScheme.dark(
    primary: Surfaces.accent,
    onPrimary: Color(0xFF07231A),
    secondary: Surfaces.accentDim,
    surface: Surfaces.panel,
    onSurface: Surfaces.ink,
    error: Surfaces.warn,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Surfaces.ground,
    visualDensity: VisualDensity.compact,
    dividerTheme: const DividerThemeData(color: Surfaces.line, space: 1, thickness: 1),
    textTheme: const TextTheme(
      bodyMedium: Type.body,
      bodySmall: Type.caption,
      titleMedium: Type.title,
    ),
    sliderTheme: const SliderThemeData(
      trackHeight: 3,
      activeTrackColor: Surfaces.accent,
      inactiveTrackColor: Surfaces.line,
      thumbColor: Surfaces.accent,
      overlayShape: RoundSliderOverlayShape(overlayRadius: 12),
    ),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      filled: true,
      fillColor: Surfaces.viewport,
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
      hintStyle: Type.caption,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: const BorderSide(color: Surfaces.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: const BorderSide(color: Surfaces.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(7),
        borderSide: const BorderSide(color: Surfaces.accentDim),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        side: const BorderSide(color: Surfaces.line),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        textStyle: const TextStyle(fontSize: 12.5),
      ),
    ),
    dropdownMenuTheme: const DropdownMenuThemeData(
      textStyle: TextStyle(fontSize: 12.5),
    ),
    listTileTheme: const ListTileThemeData(
      dense: true,
      selectedTileColor: Color(0x226FD3A0),
      contentPadding: EdgeInsets.symmetric(horizontal: Insets.md, vertical: 2),
    ),
    expansionTileTheme: const ExpansionTileThemeData(
      iconColor: Surfaces.inkDim,
      collapsedIconColor: Surfaces.inkFaint,
      textColor: Surfaces.ink,
      collapsedTextColor: Surfaces.ink,
    ),
  );
}

/// A section heading. Used everywhere a group of controls starts, so the eye can
/// skip whole groups instead of reading every label.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.top = Insets.lg});
  final String text;
  final double top;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(top: top, bottom: Insets.sm),
        child: Text(text.toUpperCase(), style: Type.section),
      );
}
