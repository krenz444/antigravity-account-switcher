fn main() {
    slint_build::compile("ui/app.slint").unwrap();

    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("app_icon.ico");
        let _ = res.compile();
    }
}
