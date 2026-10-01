using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Reflection.AssemblyTitle("DuyTris Cloudflare & Backend Manager")]
[assembly: System.Reflection.AssemblyDescription("Quan ly ket noi Cloudflare Tunnel va Backend Flask cho DuyTris Downloader")]
[assembly: System.Reflection.AssemblyCompany("DuyTris")]
[assembly: System.Reflection.AssemblyProduct("DuyTris System Manager")]
[assembly: System.Reflection.AssemblyCopyright("Copyright \u00A9 2026 DuyTris")]
[assembly: System.Reflection.AssemblyVersion("2.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("2.0.0.0")]

namespace DuyTrisManager
{
    public static class GraphicsUtils
    {
        public static GraphicsPath GetRoundedPath(Rectangle rect, int radius)
        {
            GraphicsPath path = new GraphicsPath();
            float d = radius * 2F;
            if (d > rect.Width) d = rect.Width;
            if (d > rect.Height) d = rect.Height;

            path.AddArc(rect.X, rect.Y, d, d, 180, 90);
            path.AddArc(rect.Right - d, rect.Y, d, d, 270, 90);
            path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
            path.AddArc(rect.X, rect.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    public class RoundedButton : Button
    {
        public int BorderRadius { get; set; }
        public Color NormalColor { get; set; }
        public Color HoverColor { get; set; }
        public Color PressColor { get; set; }
        public Color BorderColor { get; set; }
        public string IconText { get; set; }
        public string ButtonText { get; set; }
        public float CustomFontSize { get; set; }

        private bool isHovered = false;
        private bool isPressed = false;

        public RoundedButton()
        {
            this.BorderRadius = 8;
            this.NormalColor = Color.FromArgb(59, 130, 246);
            this.HoverColor = Color.FromArgb(37, 99, 235);
            this.PressColor = Color.FromArgb(29, 78, 216);
            this.BorderColor = Color.Transparent;
            this.IconText = "";
            this.ButtonText = "";
            this.CustomFontSize = 8.8f;

            this.FlatStyle = FlatStyle.Flat;
            this.FlatAppearance.BorderSize = 0;
            this.DoubleBuffered = true;
            this.Cursor = Cursors.Hand;
            this.UseMnemonic = false;
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            isHovered = true;
            Invalidate();
            base.OnMouseEnter(e);
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            isHovered = false;
            Invalidate();
            base.OnMouseLeave(e);
        }

        protected override void OnMouseDown(MouseEventArgs mevent)
        {
            isPressed = true;
            Invalidate();
            base.OnMouseDown(mevent);
        }

        protected override void OnMouseUp(MouseEventArgs mevent)
        {
            isPressed = false;
            Invalidate();
            base.OnMouseUp(mevent);
        }

        protected override void OnPaint(PaintEventArgs pevent)
        {
            Graphics g = pevent.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
            Rectangle rect = new Rectangle(0, 0, Width, Height);

            using (GraphicsPath path = GraphicsUtils.GetRoundedPath(rect, BorderRadius))
            {
                this.Region = new Region(path);

                Color bg = NormalColor;
                if (!Enabled) bg = Color.FromArgb(51, 65, 85);
                else if (isPressed) bg = PressColor;
                else if (isHovered) bg = HoverColor;

                using (SolidBrush brush = new SolidBrush(bg))
                {
                    g.FillPath(brush, path);
                }

                if (BorderColor != Color.Transparent)
                {
                    using (Pen pen = new Pen(BorderColor, 1.2f))
                    {
                        g.DrawPath(pen, path);
                    }
                }

                using (Font iconFont = new Font("Segoe UI Symbol", 10.5f, FontStyle.Bold))
                using (Font textFont = new Font("Segoe UI", CustomFontSize, FontStyle.Bold))
                {
                    string icon = IconText ?? "";
                    string text = !string.IsNullOrEmpty(ButtonText) ? ButtonText : Text;

                    Size textSize = TextRenderer.MeasureText(g, text, textFont, Size.Empty, TextFormatFlags.NoPrefix);
                    int iconWidth = string.IsNullOrEmpty(icon) ? 0 : 20;
                    int gap = string.IsNullOrEmpty(icon) ? 0 : 7;
                    int totalW = iconWidth + gap + textSize.Width;

                    int startX = (Width - totalW) / 2;
                    if (startX < 8) startX = 8;

                    if (!string.IsNullOrEmpty(icon))
                    {
                        Rectangle iconRect = new Rectangle(startX, 0, iconWidth, Height);
                        TextRenderer.DrawText(g, icon, iconFont, iconRect, ForeColor,
                            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
                    }

                    Rectangle textRect = new Rectangle(startX + iconWidth + gap, 0, Width - (startX + iconWidth + gap) - 4, Height);
                    TextRenderer.DrawText(g, text, textFont, textRect, ForeColor,
                        TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
                }
            }
        }
    }

    public class RoundedPanel : Panel
    {
        public int BorderRadius { get; set; }
        public Color BorderColor { get; set; }

        public RoundedPanel()
        {
            this.BorderRadius = 10;
            this.BorderColor = Color.FromArgb(51, 65, 85);
            this.DoubleBuffered = true;
            this.BackColor = Color.FromArgb(30, 41, 59);
        }

        protected override void OnPaint(PaintEventArgs pevent)
        {
            Graphics g = pevent.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            Rectangle rect = new Rectangle(0, 0, Width - 1, Height - 1);

            using (GraphicsPath path = GraphicsUtils.GetRoundedPath(rect, BorderRadius))
            {
                this.Region = new Region(path);

                using (SolidBrush brush = new SolidBrush(BackColor))
                {
                    g.FillPath(brush, path);
                }

                if (BorderColor != Color.Transparent)
                {
                    using (Pen pen = new Pen(BorderColor, 1.2f))
                    {
                        g.DrawPath(pen, path);
                    }
                }
            }
            base.OnPaint(pevent);
        }
    }

    public class MainForm : Form
    {
        private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupApprovedKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";
        private const string AppRegistryName = "DuyTris Video Manager";
        private const string DomainUrl = "https://dgpelectric.top";
        private const string SubDomainUrl = "https://toolvideo.dgpelectric.top";
        private const int BackendPort = 9123;

        private Label lblHeaderTitle;
        private Label lblHeaderSub;
        private Label lblHeaderDomain;
        private RoundedButton btnPin;

        private RoundedPanel pnlCardBackend;
        private Label lblTitleBackend;
        private Label lblStatusBackend;

        private RoundedPanel pnlCardTunnel;
        private Label lblTitleTunnel;
        private Label lblStatusTunnel;

        private RoundedPanel pnlCardApi;
        private Label lblTitleApi;
        private Label lblStatusApi;

        private RoundedPanel pnlCardDomain;
        private Label lblTitleDomain;
        private Label lblStatusDomain;

        private RoundedPanel pnlCardStartup;
        private Label lblTitleStartup;
        private Label lblStatusStartup;

        private RoundedButton btnStart;
        private RoundedButton btnStop;
        private RoundedButton btnRestart;
        private RoundedButton btnToggleStartup;
        private RoundedButton btnOpenBrowser;
        private RoundedButton btnRefresh;

        private RoundedPanel pnlLog;
        private Label lblLogIcon;
        private Label lblLogText;
        private Timer refreshTimer;

        private string baseDir;
        private bool isUpdating = false;
        private bool isAutoStart = false;
        private bool isPinned = false;

        [STAThread]
        public static void Main(string[] args)
        {
            AppDomain.CurrentDomain.UnhandledException += (s, e) => {
                try {
                    File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "setup_error.log"), "UnhandledException: " + e.ExceptionObject.ToString());
                } catch {}
            };
            Application.ThreadException += (s, e) => {
                try {
                    File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "setup_error.log"), "ThreadException: " + e.Exception.ToString());
                } catch {}
            };
            TaskScheduler.UnobservedTaskException += (s, e) => {
                try {
                    File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "setup_error.log"), "TaskException: " + e.Exception.ToString());
                } catch {}
            };

            try {
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072 | (SecurityProtocolType)768 | SecurityProtocolType.Tls;
                ServicePointManager.DefaultConnectionLimit = 50;
            } catch {}

            bool autoStart = false;
            if (args != null)
            {
                foreach (var a in args)
                {
                    if (string.Equals(a, "--autostart", StringComparison.OrdinalIgnoreCase))
                    {
                        autoStart = true;
                        break;
                    }
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm(autoStart));
        }

        public MainForm(bool autoStart)
        {
            this.isAutoStart = autoStart;
            baseDir = AppDomain.CurrentDomain.BaseDirectory;

            InitializeComponent();

            refreshTimer = new Timer();
            refreshTimer.Interval = 3000;
            refreshTimer.Tick += async (s, e) => await RefreshStatusAsync();
            refreshTimer.Start();

            this.Load += async (s, e) => {
                this.WindowState = FormWindowState.Normal;
                this.BringToFront();
                this.Activate();

                await RefreshStatusAsync();

                if (isAutoStart)
                {
                    this.TopMost = true;
                    var t = new Timer();
                    t.Interval = 1500;
                    t.Tick += (ts, te) => {
                        this.TopMost = isPinned;
                        t.Stop();
                        t.Dispose();
                    };
                    t.Start();

                    lblLogIcon.Text = "\u23F3";
                    lblLogIcon.ForeColor = Color.FromArgb(251, 191, 36);
                    lblLogText.Text = "Đang tự động khởi động Backend & Cloudflare Tunnel khi mở máy...";

                    bool be = CheckPort(BackendPort);
                    bool cf = Process.GetProcessesByName("cloudflared").Length > 0;
                    if (!be || !cf)
                    {
                        await HandleStartAsync();
                    }
                }
            };
        }

        private void InitializeComponent()
        {
            this.Text = "DuyTris - Quản Lý Kết Nối Cloudflare & Backend";
            this.ClientSize = new Size(560, 538);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedSingle;
            this.MaximizeBox = false;
            this.BackColor = Color.FromArgb(15, 23, 42); // Slate 900
            this.ForeColor = Color.White;
            this.Font = new Font("Segoe UI", 9f, FontStyle.Regular);

            try
            {
                string iconPath = Path.Combine(baseDir, @"img\logo.ico");
                if (File.Exists(iconPath))
                {
                    this.Icon = new Icon(iconPath);
                }
            }
            catch {}

            int contentW = 520;
            int marginX = 20;

            // 1. Header Panel
            RoundedPanel pnlHeader = new RoundedPanel();
            pnlHeader.Location = new Point(marginX, 14);
            pnlHeader.Size = new Size(contentW, 76);
            pnlHeader.BorderRadius = 10;
            pnlHeader.BorderColor = Color.FromArgb(51, 65, 85);

            lblHeaderTitle = new Label();
            lblHeaderTitle.Text = "\u26A1 DUYTRIS SYSTEM MANAGER (BACKEND + CLOUDFLARE)";
            lblHeaderTitle.Font = new Font("Segoe UI", 10.2f, FontStyle.Bold);
            lblHeaderTitle.ForeColor = Color.FromArgb(248, 250, 252);
            lblHeaderTitle.Location = new Point(14, 9);
            lblHeaderTitle.AutoSize = true;
            lblHeaderTitle.UseMnemonic = false;

            lblHeaderSub = new Label();
            lblHeaderSub.Text = "Quản lý kết nối ngầm Backend & Tên miền Cloudflare khi bật máy";
            lblHeaderSub.Font = new Font("Segoe UI", 8.5f);
            lblHeaderSub.ForeColor = Color.FromArgb(148, 163, 184);
            lblHeaderSub.Location = new Point(15, 33);
            lblHeaderSub.AutoSize = true;
            lblHeaderSub.UseMnemonic = false;

            lblHeaderDomain = new Label();
            lblHeaderDomain.Text = "\U0001F310 Tên miền: " + DomainUrl + "  \u279C  Port " + BackendPort;
            lblHeaderDomain.Font = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            lblHeaderDomain.ForeColor = Color.FromArgb(56, 189, 248);
            lblHeaderDomain.Location = new Point(15, 52);
            lblHeaderDomain.AutoSize = true;
            lblHeaderDomain.UseMnemonic = false;

            // Pin Button
            btnPin = new RoundedButton();
            btnPin.Location = new Point(contentW - 82, 10);
            btnPin.Size = new Size(72, 26);
            btnPin.BorderRadius = 6;
            btnPin.IconText = "\uD83D\uDCCC";
            btnPin.ButtonText = "Ghim";
            btnPin.CustomFontSize = 8f;
            btnPin.NormalColor = Color.FromArgb(51, 65, 85);
            btnPin.HoverColor = Color.FromArgb(71, 85, 105);
            btnPin.PressColor = Color.FromArgb(30, 41, 59);
            btnPin.Click += (s, e) => {
                isPinned = !isPinned;
                this.TopMost = isPinned;
                if (isPinned)
                {
                    btnPin.ButtonText = "Đã ghim";
                    btnPin.NormalColor = Color.FromArgb(217, 119, 6);
                    btnPin.HoverColor = Color.FromArgb(180, 83, 9);
                }
                else
                {
                    btnPin.ButtonText = "Ghim";
                    btnPin.NormalColor = Color.FromArgb(51, 65, 85);
                    btnPin.HoverColor = Color.FromArgb(71, 85, 105);
                }
            };

            pnlHeader.Controls.Add(lblHeaderTitle);
            pnlHeader.Controls.Add(lblHeaderSub);
            pnlHeader.Controls.Add(lblHeaderDomain);
            pnlHeader.Controls.Add(btnPin);
            this.Controls.Add(pnlHeader);

            // 2. Status Cards
            int cardW = 252;
            int cardH = 58;
            int col2X = marginX + cardW + 16;
            int row1Y = 98;
            int row2Y = 162;
            int row3Y = 226;

            // Row 1: Backend & Tunnel
            pnlCardBackend = CreateCard(marginX, row1Y, cardW, cardH, out lblTitleBackend, out lblStatusBackend,
                "1. Backend Flask (Local)", "Đang kiểm tra...", Color.FromArgb(148, 163, 184));
            this.Controls.Add(pnlCardBackend);

            pnlCardTunnel = CreateCard(col2X, row1Y, cardW, cardH, out lblTitleTunnel, out lblStatusTunnel,
                "2. Cloudflare Tunnel (dgpelectric.top)", "Đang kiểm tra...", Color.FromArgb(148, 163, 184));
            this.Controls.Add(pnlCardTunnel);

            // Row 2: API/SocketIO & Domain
            pnlCardApi = CreateCard(marginX, row2Y, cardW, cardH, out lblTitleApi, out lblStatusApi,
                "3. Trạng Thái API & SocketIO", "Đang kiểm tra...", Color.FromArgb(148, 163, 184));
            this.Controls.Add(pnlCardApi);

            pnlCardDomain = CreateCard(col2X, row2Y, cardW, cardH, out lblTitleDomain, out lblStatusDomain,
                "4. Tên Miền Ngoài", "Đang kiểm tra...", Color.FromArgb(148, 163, 184));
            this.Controls.Add(pnlCardDomain);

            // Row 3: Startup
            pnlCardStartup = CreateCard(marginX, row3Y, contentW, 50, out lblTitleStartup, out lblStatusStartup,
                "5. Tự Động Mở Khi Bật Máy (Task Manager Startup)", "Đang kiểm tra...", Color.FromArgb(148, 163, 184));
            this.Controls.Add(pnlCardStartup);

            // 3. Action Buttons
            int btnRow1Y = 284;
            int btnRow2Y = 338;
            int btnRow3Y = 392;
            int btnH = 46;

            // Button Start
            btnStart = new RoundedButton();
            btnStart.Location = new Point(marginX, btnRow1Y);
            btnStart.Size = new Size(cardW, btnH);
            btnStart.IconText = "\u25B6";
            btnStart.ButtonText = "BẬT KẾT NỐI (Chạy ngầm)";
            btnStart.CustomFontSize = 8.8f;
            btnStart.NormalColor = Color.FromArgb(16, 185, 129); // Emerald 500
            btnStart.HoverColor = Color.FromArgb(5, 150, 105);   // Emerald 600
            btnStart.PressColor = Color.FromArgb(4, 120, 87);    // Emerald 700
            btnStart.Click += async (s, e) => await HandleStartAsync();
            this.Controls.Add(btnStart);

            // Button Stop
            btnStop = new RoundedButton();
            btnStop.Location = new Point(col2X, btnRow1Y);
            btnStop.Size = new Size(cardW, btnH);
            btnStop.IconText = "\u25A0";
            btnStop.ButtonText = "TẮT KẾT NỐI";
            btnStop.CustomFontSize = 8.8f;
            btnStop.NormalColor = Color.FromArgb(239, 68, 68); // Red 500
            btnStop.HoverColor = Color.FromArgb(220, 38, 38);  // Red 600
            btnStop.PressColor = Color.FromArgb(185, 28, 28);  // Red 700
            btnStop.Click += async (s, e) => await HandleStopAsync();
            this.Controls.Add(btnStop);

            // Button Restart
            btnRestart = new RoundedButton();
            btnRestart.Location = new Point(marginX, btnRow2Y);
            btnRestart.Size = new Size(cardW, btnH);
            btnRestart.IconText = "\u21BB";
            btnRestart.ButtonText = "KHỞI ĐỘNG LẠI";
            btnRestart.CustomFontSize = 8.8f;
            btnRestart.NormalColor = Color.FromArgb(59, 130, 246); // Blue 500
            btnRestart.HoverColor = Color.FromArgb(37, 99, 235);   // Blue 600
            btnRestart.PressColor = Color.FromArgb(29, 78, 216);   // Blue 700
            btnRestart.Click += async (s, e) => await HandleRestartAsync();
            this.Controls.Add(btnRestart);

            // Button Toggle Startup
            btnToggleStartup = new RoundedButton();
            btnToggleStartup.Location = new Point(col2X, btnRow2Y);
            btnToggleStartup.Size = new Size(cardW, btnH);
            btnToggleStartup.IconText = "\u2699";
            btnToggleStartup.ButtonText = "TỰ ĐỘNG MỞ KHI BẬT MÁY";
            btnToggleStartup.CustomFontSize = 8.5f;
            btnToggleStartup.NormalColor = Color.FromArgb(139, 92, 246); // Purple 500
            btnToggleStartup.HoverColor = Color.FromArgb(124, 58, 237);  // Purple 600
            btnToggleStartup.PressColor = Color.FromArgb(109, 40, 217);  // Purple 700
            btnToggleStartup.Click += async (s, e) => await HandleToggleStartupAsync();
            this.Controls.Add(btnToggleStartup);

            // Row 3: Open Browser & Refresh
            int browserBtnW = 356;
            int refreshBtnW = contentW - browserBtnW - 14;

            btnOpenBrowser = new RoundedButton();
            btnOpenBrowser.Location = new Point(marginX, btnRow3Y);
            btnOpenBrowser.Size = new Size(browserBtnW, btnH);
            btnOpenBrowser.IconText = "\u2197";
            btnOpenBrowser.ButtonText = "MỞ TRANG QUẢN TRỊ (dgpelectric.top)";
            btnOpenBrowser.CustomFontSize = 8.3f;
            btnOpenBrowser.NormalColor = Color.FromArgb(2, 132, 199); // Sky 600
            btnOpenBrowser.HoverColor = Color.FromArgb(3, 105, 161);  // Sky 700
            btnOpenBrowser.PressColor = Color.FromArgb(7, 89, 133);   // Sky 800
            btnOpenBrowser.Click += (s, e) => {
                try { Process.Start(DomainUrl); }
                catch (Exception ex) { MessageBox.Show("Không thể mở trình duyệt: " + ex.Message); }
            };
            this.Controls.Add(btnOpenBrowser);

            btnRefresh = new RoundedButton();
            btnRefresh.Location = new Point(marginX + browserBtnW + 14, btnRow3Y);
            btnRefresh.Size = new Size(refreshBtnW, btnH);
            btnRefresh.IconText = "\u27F3";
            btnRefresh.ButtonText = "LÀM MỚI";
            btnRefresh.CustomFontSize = 8.8f;
            btnRefresh.NormalColor = Color.FromArgb(71, 85, 105); // Slate 600
            btnRefresh.HoverColor = Color.FromArgb(100, 116, 139); // Slate 500
            btnRefresh.PressColor = Color.FromArgb(51, 65, 85);   // Slate 700
            btnRefresh.Click += async (s, e) => await RefreshStatusAsync();
            this.Controls.Add(btnRefresh);

            // 4. Status / Log Panel
            int logY = 448;
            int logH = 72;

            pnlLog = new RoundedPanel();
            pnlLog.Location = new Point(marginX, logY);
            pnlLog.Size = new Size(contentW, logH);
            pnlLog.BorderRadius = 10;
            pnlLog.BorderColor = Color.FromArgb(51, 65, 85);
            pnlLog.BackColor = Color.FromArgb(30, 41, 59);

            lblLogIcon = new Label();
            lblLogIcon.Text = "\u2139";
            lblLogIcon.Font = new Font("Segoe UI Symbol", 13f, FontStyle.Bold);
            lblLogIcon.ForeColor = Color.FromArgb(56, 189, 248);
            lblLogIcon.Location = new Point(14, 20);
            lblLogIcon.Size = new Size(24, 28);
            lblLogIcon.TextAlign = ContentAlignment.MiddleCenter;
            lblLogIcon.UseMnemonic = false;

            lblLogText = new Label();
            lblLogText.Location = new Point(44, 10);
            lblLogText.Size = new Size(contentW - 55, 52);
            lblLogText.ForeColor = Color.FromArgb(226, 232, 240);
            lblLogText.Font = new Font("Segoe UI", 8.8f);
            lblLogText.Text = "Hệ thống đang kiểm tra trạng thái hoạt động...";
            lblLogText.TextAlign = ContentAlignment.MiddleLeft;
            lblLogText.UseMnemonic = false;

            pnlLog.Controls.Add(lblLogIcon);
            pnlLog.Controls.Add(lblLogText);
            this.Controls.Add(pnlLog);
        }

        private RoundedPanel CreateCard(int x, int y, int w, int h, out Label title, out Label status, string titleText, string initialStatus, Color statusColor)
        {
            RoundedPanel pnl = new RoundedPanel();
            pnl.Location = new Point(x, y);
            pnl.Size = new Size(w, h);
            pnl.BorderRadius = 8;
            pnl.BorderColor = Color.FromArgb(51, 65, 85);
            pnl.BackColor = Color.FromArgb(30, 41, 59);

            title = new Label();
            title.Text = titleText;
            title.Font = new Font("Segoe UI", 8.2f, FontStyle.Regular);
            title.ForeColor = Color.FromArgb(148, 163, 184);
            title.Location = new Point(12, 6);
            title.AutoSize = true;
            title.UseMnemonic = false;

            status = new Label();
            status.Text = initialStatus;
            status.Font = new Font("Segoe UI", 8.8f, FontStyle.Bold);
            status.ForeColor = statusColor;
            status.Location = new Point(12, 27);
            status.AutoSize = true;
            status.UseMnemonic = false;

            pnl.Controls.Add(title);
            pnl.Controls.Add(status);
            return pnl;
        }

        private bool IsAutoStartConfigured()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKeyPath, false))
                {
                    if (key != null && key.GetValue(AppRegistryName) != null)
                        return true;
                }

                string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                string lnk = Path.Combine(appData, @"Microsoft\Windows\Start Menu\Programs\Startup\DuyTris_Video_Manager.lnk");
                return File.Exists(lnk);
            }
            catch { return false; }
        }

        private void SetAutoStart(bool enable)
        {
            try
            {
                string exePath = Path.Combine(baseDir, "setup.exe");
                string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                string startupFolder = Path.Combine(appData, @"Microsoft\Windows\Start Menu\Programs\Startup");
                string shortcutPath = Path.Combine(startupFolder, "DuyTris_Video_Manager.lnk");

                // 1. Registry Run
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true))
                {
                    if (key != null)
                    {
                        if (enable)
                        {
                            key.SetValue(AppRegistryName, "\"" + exePath + "\" --autostart");
                            try
                            {
                                using (RegistryKey saKey = Registry.CurrentUser.OpenSubKey(StartupApprovedKeyPath, true))
                                {
                                    if (saKey != null)
                                    {
                                        byte[] enabledBytes = new byte[] { 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
                                        saKey.SetValue(AppRegistryName, enabledBytes, RegistryValueKind.Binary);
                                    }
                                }
                            }
                            catch {}
                        }
                        else
                        {
                            key.DeleteValue(AppRegistryName, false);
                            try
                            {
                                using (RegistryKey saKey = Registry.CurrentUser.OpenSubKey(StartupApprovedKeyPath, true))
                                {
                                    if (saKey != null) saKey.DeleteValue(AppRegistryName, false);
                                }
                            }
                            catch {}
                        }
                    }
                }

                // 2. Startup Folder Shortcut
                if (Directory.Exists(startupFolder))
                {
                    string[] oldFiles = Directory.GetFiles(startupFolder, "DuyTris_*");
                    foreach (var f in oldFiles)
                    {
                        try { File.Delete(f); } catch {}
                    }

                    if (enable)
                    {
                        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                        if (shellType != null)
                        {
                            dynamic shell = Activator.CreateInstance(shellType);
                            dynamic shortcut = shell.CreateShortcut(shortcutPath);
                            shortcut.TargetPath = exePath;
                            shortcut.Arguments = "--autostart";
                            shortcut.WorkingDirectory = baseDir;
                            shortcut.Description = "Tu dong mo DuyTris Cloudflare & Backend Manager khi bat may";
                            shortcut.Save();
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("Không thể thay đổi thiết lập tự khởi động: " + ex.Message);
            }
        }

        private async Task RefreshStatusAsync()
        {
            if (isUpdating) return;
            isUpdating = true;

            try
            {
                // 1. Check Backend Port 9123
                bool beOpen = await Task.Run(() => CheckPort(BackendPort));
                if (beOpen)
                {
                    lblStatusBackend.Text = "\u25CF  Đang chạy (Port " + BackendPort + ")";
                    lblStatusBackend.ForeColor = Color.FromArgb(52, 211, 153);
                    lblStatusApi.Text = "\u25CF  Sẵn sàng phục vụ";
                    lblStatusApi.ForeColor = Color.FromArgb(52, 211, 153);
                }
                else
                {
                    lblStatusBackend.Text = "\u25CF  Đã dừng";
                    lblStatusBackend.ForeColor = Color.FromArgb(248, 113, 113);
                    lblStatusApi.Text = "\u25CF  Chưa sẵn sàng";
                    lblStatusApi.ForeColor = Color.FromArgb(248, 113, 113);
                }

                // 2. Check Cloudflare Tunnel process
                bool cfRunning = await Task.Run(() => {
                    var procs = Process.GetProcessesByName("cloudflared");
                    return procs != null && procs.Length > 0;
                });
                if (cfRunning)
                {
                    lblStatusTunnel.Text = "\u25CF  Đang kết nối";
                    lblStatusTunnel.ForeColor = Color.FromArgb(52, 211, 153);
                }
                else
                {
                    lblStatusTunnel.Text = "\u25CF  Đã tắt";
                    lblStatusTunnel.ForeColor = Color.FromArgb(248, 113, 113);
                }

                // 3. Check Auto-start
                bool isStartup = IsAutoStartConfigured();
                if (isStartup)
                {
                    lblStatusStartup.Text = "\u25CF  Đang bật";
                    lblStatusStartup.ForeColor = Color.FromArgb(52, 211, 153);
                    btnToggleStartup.ButtonText = "TẮT TỰ ĐỘNG MỞ";
                    btnToggleStartup.NormalColor = Color.FromArgb(100, 116, 139);
                    btnToggleStartup.HoverColor = Color.FromArgb(71, 85, 105);
                    btnToggleStartup.PressColor = Color.FromArgb(51, 65, 85);
                }
                else
                {
                    lblStatusStartup.Text = "\u25CB  Đã tắt";
                    lblStatusStartup.ForeColor = Color.FromArgb(148, 163, 184);
                    btnToggleStartup.ButtonText = "BẬT TỰ ĐỘNG MỞ";
                    btnToggleStartup.NormalColor = Color.FromArgb(139, 92, 246);
                    btnToggleStartup.HoverColor = Color.FromArgb(124, 58, 237);
                    btnToggleStartup.PressColor = Color.FromArgb(109, 40, 217);
                }

                // 4. Check External Domain
                if (beOpen && cfRunning)
                {
                    bool domainOk = await Task.Run(() => CheckDomain());
                    if (domainOk)
                    {
                        lblStatusDomain.Text = "\u25CF  Online (200 OK)";
                        lblStatusDomain.ForeColor = Color.FromArgb(52, 211, 153);
                        lblLogIcon.Text = "\u2713";
                        lblLogIcon.ForeColor = Color.FromArgb(52, 211, 153);
                        lblLogText.Text = "[SẴN SÀNG] Backend & Cloudflare đang hoạt động ngầm ổn định.\nTên miền " + DomainUrl + " đã kết nối thành công!";
                    }
                    else
                    {
                        lblStatusDomain.Text = "\u25CF  Đang định tuyến...";
                        lblStatusDomain.ForeColor = Color.FromArgb(251, 191, 36);
                        lblLogIcon.Text = "\u23F3";
                        lblLogIcon.ForeColor = Color.FromArgb(251, 191, 36);
                        lblLogText.Text = "[ĐANG KẾT NỐI] Tunnel đang đồng bộ tới Cloudflare Edge...";
                    }
                }
                else
                {
                    lblStatusDomain.Text = "\u25CF  Offline (Chưa kết nối)";
                    lblStatusDomain.ForeColor = Color.FromArgb(248, 113, 113);
                    lblLogIcon.Text = "\u2139";
                    lblLogIcon.ForeColor = Color.FromArgb(56, 189, 248);
                    lblLogText.Text = "[THÔNG BÁO] Kết nối đang tắt. Nhấn nút [BẬT KẾT NỐI] bên trên để kích hoạt.";
                }
            }
            catch (Exception ex)
            {
                lblLogIcon.Text = "\u26A0";
                lblLogIcon.ForeColor = Color.FromArgb(248, 113, 113);
                lblLogText.Text = "Lỗi kiểm tra trạng thái: " + ex.Message;
            }
            finally
            {
                isUpdating = false;
            }
        }

        private bool CheckPort(int port)
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var result = client.BeginConnect("127.0.0.1", port, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(400);
                    if (success)
                    {
                        client.EndConnect(result);
                        return true;
                    }
                    return false;
                }
            }
            catch { return false; }
        }

        private bool CheckDomain()
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(DomainUrl + "/api/files/completed");
                req.Timeout = 3000;
                req.ReadWriteTimeout = 3000;
                req.Method = "GET";
                req.UserAgent = "DuyTrisSetupManager";
                using (var resp = (HttpWebResponse)req.GetResponse())
                {
                    return (int)resp.StatusCode < 500;
                }
            }
            catch (WebException wex)
            {
                using (var r = wex.Response as HttpWebResponse)
                {
                    if (r != null)
                    {
                        int code = (int)r.StatusCode;
                        return code < 500;
                    }
                }
                try
                {
                    var req2 = (HttpWebRequest)WebRequest.Create(SubDomainUrl + "/api/files/completed");
                    req2.Timeout = 3000;
                    req2.ReadWriteTimeout = 3000;
                    req2.Method = "GET";
                    req2.UserAgent = "DuyTrisSetupManager";
                    using (var resp2 = (HttpWebResponse)req2.GetResponse())
                    {
                        return (int)resp2.StatusCode < 500;
                    }
                }
                catch { return false; }
            }
            catch { return false; }
        }

        private string FindPythonExe()
        {
            string venvPy = Path.Combine(baseDir, @".venv\Scripts\python.exe");
            if (File.Exists(venvPy)) return venvPy;

            string localPy = Path.Combine(baseDir, @"python.exe");
            if (File.Exists(localPy)) return localPy;

            return "python";
        }

        private string FindCloudflaredExe()
        {
            string inTools = Path.Combine(baseDir, @"tools\cloudflared.exe");
            if (File.Exists(inTools)) return inTools;

            string p86 = @"C:\Program Files (x86)\cloudflared\cloudflared.exe";
            if (File.Exists(p86)) return p86;

            string p64 = @"C:\Program Files\cloudflared\cloudflared.exe";
            if (File.Exists(p64)) return p64;

            return "cloudflared";
        }

        private async Task HandleStartAsync()
        {
            lblLogIcon.Text = "\u23F3";
            lblLogIcon.ForeColor = Color.FromArgb(251, 191, 36);
            lblLogText.Text = "Đang khởi động Backend Server & Cloudflare Tunnel ngầm...";
            btnStart.Enabled = false;

            await Task.Run(() => {
                // 1. Khoi dong Backend Server (Port 9123) neu chua chay
                if (!CheckPort(BackendPort))
                {
                    string pythonExe = FindPythonExe();
                    string runFlask = Path.Combine(baseDir, "run_flask.py");
                    if (File.Exists(runFlask))
                    {
                        ProcessStartInfo pyPsi = new ProcessStartInfo();
                        pyPsi.FileName = pythonExe;
                        pyPsi.Arguments = "\"" + runFlask + "\"";
                        pyPsi.WorkingDirectory = baseDir;
                        pyPsi.EnvironmentVariables["OPEN_BROWSER"] = "0";
                        pyPsi.EnvironmentVariables["FLASK_PORT"] = BackendPort.ToString();
                        pyPsi.UseShellExecute = false;
                        pyPsi.CreateNoWindow = true;
                        pyPsi.WindowStyle = ProcessWindowStyle.Hidden;
                        Process.Start(pyPsi);
                    }
                }

                // 2. Khoi dong Cloudflare Tunnel neu chua chay
                var cfProcs = Process.GetProcessesByName("cloudflared");
                if (cfProcs == null || cfProcs.Length == 0)
                {
                    string cfExe = FindCloudflaredExe();
                    string configPath = Path.Combine(baseDir, @"tools\tunnel_config.yml");
                    if (File.Exists(configPath))
                    {
                        ProcessStartInfo cfPsi = new ProcessStartInfo();
                        cfPsi.FileName = cfExe;
                        cfPsi.Arguments = "--config \"" + configPath + "\" tunnel run aide-backend";
                        cfPsi.WorkingDirectory = baseDir;
                        cfPsi.UseShellExecute = false;
                        cfPsi.CreateNoWindow = true;
                        cfPsi.WindowStyle = ProcessWindowStyle.Hidden;
                        Process.Start(cfPsi);
                    }
                }
            });

            await Task.Delay(4500);
            btnStart.Enabled = true;
            await RefreshStatusAsync();
        }

        private async Task HandleStopAsync()
        {
            lblLogIcon.Text = "\u23F3";
            lblLogIcon.ForeColor = Color.FromArgb(251, 191, 36);
            lblLogText.Text = "Đang dừng và giải phóng Backend & Cloudflare Tunnel...";
            btnStop.Enabled = false;

            await Task.Run(() => {
                // 1. Chay stop_backend_and_tunnel.bat neu co
                string bat = Path.Combine(baseDir, "stop_backend_and_tunnel.bat");
                if (File.Exists(bat))
                {
                    try {
                        ProcessStartInfo psi = new ProcessStartInfo(bat, "--silent");
                        psi.WorkingDirectory = baseDir;
                        psi.WindowStyle = ProcessWindowStyle.Hidden;
                        psi.CreateNoWindow = true;
                        var p = Process.Start(psi);
                        if (p != null) p.WaitForExit(4000);
                    } catch {}
                }

                // 2. Kill cloudflared process truc tiep
                try
                {
                    foreach (var p in Process.GetProcessesByName("cloudflared"))
                    {
                        try { p.Kill(); } catch {}
                    }
                }
                catch {}

                // 3. Giai phong port 9123
                try
                {
                    ProcessStartInfo netPsi = new ProcessStartInfo("cmd.exe", "/c for /f \"tokens=5\" %a in ('netstat -aon ^| findstr :" + BackendPort + " ^| findstr LISTENING') do taskkill /F /PID %a");
                    netPsi.WindowStyle = ProcessWindowStyle.Hidden;
                    netPsi.CreateNoWindow = true;
                    var np = Process.Start(netPsi);
                    if (np != null) np.WaitForExit(3000);
                }
                catch {}
            });

            await Task.Delay(1000);
            btnStop.Enabled = true;
            await RefreshStatusAsync();
        }

        private async Task HandleRestartAsync()
        {
            lblLogIcon.Text = "\u23F3";
            lblLogIcon.ForeColor = Color.FromArgb(251, 191, 36);
            lblLogText.Text = "Đang khởi động lại toàn bộ kết nối...";
            await HandleStopAsync();
            await Task.Delay(2000);
            await HandleStartAsync();
        }

        private async Task HandleToggleStartupAsync()
        {
            btnToggleStartup.Enabled = false;
            bool isCurrentlyOn = IsAutoStartConfigured();

            await Task.Run(() => {
                SetAutoStart(!isCurrentlyOn);
            });

            await Task.Delay(500);
            btnToggleStartup.Enabled = true;
            await RefreshStatusAsync();
        }
    }
}
