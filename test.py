from onvif import ONVIFCamera

cam = ONVIFCamera(ip, port, user, password)
media = cam.create_media_service()

profiles = media.GetProfiles()

for p in profiles:
    cfg = media.GetVideoEncoderConfiguration(
        {'ConfigurationToken': p.VideoEncoderConfiguration.token}
    )

    cfg.Resolution.Width = 1280
    cfg.Resolution.Height = 720
    cfg.RateControl.FrameRateLimit = 15
    cfg.RateControl.BitrateLimit = 2048

    print("Perfil:", p.Name)
    print("Codec:", cfg.Encoding)
    print("Resolución:", cfg.Resolution.Width, "x", cfg.Resolution.Height)
    print("FPS:", cfg.RateControl.FrameRateLimit)
    print("Bitrate:", cfg.RateControl.BitrateLimit)
    print("----")

    media.SetVideoEncoderConfiguration({
        'Configuration': cfg,
        'ForcePersistence': True
    })

    