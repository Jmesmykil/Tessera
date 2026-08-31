/// A light you drag, instead of two numbers you guess.
///
/// Azimuth and elevation are the right parameters and the wrong control. Nobody
/// knows what -35 degrees looks like on a particular character, so the numeric
/// form makes people tweak blindly and re-render until something looks right.
/// A hemisphere seen from above is the same two values in a form the hand already
/// understands: the puck's angle around the centre is azimuth, its distance from
/// the centre is elevation, and the subject is the dot in the middle.
///
/// The camera sits at the bottom of the pad because the key light rides the
/// camera by default — so "drag the light to the left" means left of frame, in
/// every direction of the orbit, which is what the user actually means.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

class LightPad extends StatelessWidget {
  const LightPad({
    super.key,
    required this.azimuth,
    required this.elevation,
    required this.onChanged,
    this.onCommit,
    this.size = 168,
  });

  /// Degrees from the camera axis; negative is to the camera's left.
  final double azimuth;

  /// Degrees above the horizon, 0..90.
  final double elevation;
  final void Function(double azimuth, double elevation) onChanged;
  final VoidCallback? onCommit;
  final double size;

  void _update(Offset local) {
    final radius = size / 2;
    final dx = local.dx - radius;
    final dy = local.dy - radius;
    final distance = math.sqrt(dx * dx + dy * dy).clamp(0.0, radius);
    // atan2 measured from straight up, so 0 is behind the subject and the puck
    // near the bottom edge is a light beside the camera.
    final a = math.atan2(dx, -dy) * 180 / math.pi;
    final e = (1.0 - distance / radius) * 90.0;
    onChanged(double.parse(a.toStringAsFixed(1)), double.parse(e.toStringAsFixed(1)));
  }

  @override
  Widget build(BuildContext context) {
    final radius = size / 2;
    final distance = (1.0 - elevation.clamp(0, 90) / 90.0) * radius;
    final radians = azimuth * math.pi / 180;
    final puck = Offset(radius + math.sin(radians) * distance,
                        radius - math.cos(radians) * distance);
    return GestureDetector(
      onPanDown: (d) => _update(d.localPosition),
      onPanUpdate: (d) => _update(d.localPosition),
      onPanEnd: (_) => onCommit?.call(),
      onTapUp: (d) { _update(d.localPosition); onCommit?.call(); },
      child: CustomPaint(
        size: Size(size, size),
        painter: _PadPainter(puck: puck,
            accent: Theme.of(context).colorScheme.primary),
      ),
    );
  }
}

class _PadPainter extends CustomPainter {
  _PadPainter({required this.puck, required this.accent});
  final Offset puck;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final centre = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2;

    canvas.drawCircle(centre, radius,
        Paint()..color = const Color(0xFF11141A)..style = PaintingStyle.fill);
    final ring = Paint()
      ..color = Colors.white12
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (final fraction in [1.0, 0.66, 0.33]) {
      canvas.drawCircle(centre, radius * fraction, ring);
    }
    canvas.drawLine(Offset(centre.dx, 0), Offset(centre.dx, size.height), ring);
    canvas.drawLine(Offset(0, centre.dy), Offset(size.width, centre.dy), ring);

    // The subject, and the camera looking at it from the near side.
    canvas.drawCircle(centre, 5, Paint()..color = Colors.white38);
    final camera = Offset(centre.dx, size.height - 8);
    canvas.drawCircle(camera, 3.5, Paint()..color = Colors.white24);
    _label(canvas, 'camera', Offset(centre.dx - 18, size.height - 22), Colors.white24);
    _label(canvas, 'behind', Offset(centre.dx - 16, 4), Colors.white12);

    // The beam, so the direction reads at a glance rather than from the numbers.
    canvas.drawLine(puck, centre,
        Paint()..color = accent.withValues(alpha: 0.45)..strokeWidth = 1.5);
    canvas.drawCircle(puck, 11, Paint()..color = accent.withValues(alpha: 0.20));
    canvas.drawCircle(puck, 6.5, Paint()..color = accent);
  }

  void _label(Canvas canvas, String text, Offset at, Color color) {
    final painter = TextPainter(
      text: TextSpan(text: text, style: TextStyle(fontSize: 8, color: color)),
      textDirection: TextDirection.ltr,
    )..layout();
    painter.paint(canvas, at);
  }

  @override
  bool shouldRepaint(_PadPainter old) => old.puck != puck;
}
